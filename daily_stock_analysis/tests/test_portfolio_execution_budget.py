"""Real temporary-ledger coverage: evidence, budget and manual order lifecycle."""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.config import Config
from src.core.portfolio_allocation import evaluate_allocation_plan
from src.services.portfolio_service import PortfolioService, PortfolioConflictError, PortfolioOversellError
from src.services.portfolio_budget_service import PortfolioBudgetService
from src.storage import DatabaseManager, PortfolioPurchaseIntent


class ExecutionBudgetTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ENV_FILE': str(Path(self.temp.name) / 'empty.env'),
                                         'DATABASE_PATH': str(Path(self.temp.name) / 'ledger.db')})
        self.env.start()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.p = PortfolioService()
        self.b = PortfolioBudgetService(self.p.repo)
        self.a = self.p.create_account(name='Test', broker=None, market='us', base_currency='USD')['id']
        self.day = datetime.now(ZoneInfo('America/New_York')).date()
        self.payload = dict(name='Core', currency='CNY', timezone='America/New_York',
                            start_date=str(self.day - timedelta(days=3)), end_date=str(self.day + timedelta(days=30)),
                            amount=10000, symbols=['QQQM', 'VOO'], ledger_complete=True, request_key='budget-1')
        self.bid = self.b.create_budget(self.a, self.payload)['id']

    def tearDown(self):
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.env.stop()
        self.temp.cleanup()

    def trade(self, **kw):
        data = dict(account_id=self.a, symbol='VOO', trade_date=self.day, side='buy', quantity=1, price=702.89)
        data.update(kw)
        return self.p.record_trade(**data)['id']

    def status(self):
        return self.b.list_status(self.a)[0]

    def intent(self, **kw):
        data = dict(symbol='VOO', quantity=2, limit_price=700, fee_reserve=2, fx_rate=7,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), request_key='intent-1')
        data.update(kw)
        return self.b.create_intent(self.bid, data)['id']

    def report(self, iid, state, revision=1):
        return self.b.set_intent_state(iid, dict(status=state, expected_revision=revision, reason='broker feedback'))

    def adjustment(self, tid, **kw):
        self.b.adjust_trade(self.bid, tid, dict(fx_rate=7, excluded=False, reason='confirmed conversion', **kw))

    def test_budget_idempotency_and_overlap(self):
        self.assertEqual(self.b.create_budget(self.a, self.payload)['id'], self.bid)
        with self.assertRaises(PortfolioConflictError):
            self.b.create_budget(self.a, {**self.payload, 'amount': 20000})
        with self.assertRaises(PortfolioConflictError):
            self.b.create_budget(self.a, {**self.payload, 'request_key': 'different'})
        self.assertEqual(self.status()['confirmed_spent'], 0)

    def test_order_plan_rejects_ambiguous_account_currency(self):
        aid = self.p.create_account(name='Mixed', broker=None, market='us', base_currency='CNY')['id']
        bid = self.b.create_budget(aid, {**self.payload, 'request_key': 'mixed-budget'})['id']
        with self.assertRaisesRegex(ValueError, 'market trading currency'):
            self.b.create_intent(bid, dict(symbol='VOO', quantity=1, limit_price=700, fee_reserve=1,
                fx_rate=1, expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), request_key='mixed-intent'))
        self.assertEqual(self.b.list_status(aid)[0]['intents'], [])

    def test_512890_no_fill_never_changes_holdings_or_spending(self):
        cn = self.p.create_account(name='CN', broker=None, market='cn', base_currency='CNY')['id']
        bid = self.b.create_budget(cn, {**self.payload, 'request_key': 'cn', 'timezone': 'Asia/Shanghai',
            'currency': 'CNY', 'symbols': ['512890'], 'amount': 15000})['id']
        iid = self.b.create_intent(bid, dict(symbol='512890', quantity=12600, limit_price=1.18,
            fee_reserve=5, fx_rate=1, expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            request_key='cn-intent'))['id']
        self.assertEqual(self.b.list_status(cn)[0]['reserved_amount'], 0)
        self.report(iid, 'submitted')
        self.assertEqual(self.b.list_status(cn)[0]['reserved_amount'], 14873)
        self.report(iid, 'expired', 2)
        s = self.b.list_status(cn)[0]
        self.assertEqual((s['confirmed_spent'], s['reserved_amount'], s['remaining_amount']), (0, 0, 15000))
        self.assertEqual(self.p.list_trade_events(account_id=cn)['total'], 0)

    def test_voo_old_holding_exclusion_and_new_fill(self):
        old = self.trade(price=707.63, fee_status='confirmed', trade_date=self.day - timedelta(days=2))
        new = self.trade(fee=1.04, fee_status='confirmed')
        self.b.adjust_trade(self.bid, old, dict(excluded=True, fx_rate=None, reason='Pre-existing holding, not this budget'))
        self.adjustment(new)
        self.assertAlmostEqual(self.status()['confirmed_spent'], (702.89 + 1.04) * 7)
        self.assertEqual(len(self.p.repo.list_trades(self.a, self.day)), 2)

    def test_unknown_fee_or_fx_blocks_remaining_budget(self):
        tid = self.trade()
        self.assertIsNone(self.status()['remaining_amount'])
        self.adjustment(tid)
        self.assertIsNone(self.status()['remaining_amount'])
        self.b.reconcile_trade(tid, dict(expected_revision=1, fee=1.04, tax=0,
            fee_status='confirmed', executed_at=None, reason='Statement'))
        self.assertAlmostEqual(self.status()['remaining_amount'], 10000 - 703.93 * 7)
        self.assertEqual(len(self.b.audit(self.a)), 3)

    def test_hal_gross_profit_is_not_verified_net_profit(self):
        buy = self.trade(symbol='HAL', quantity=10, price=32.75)
        sell = self.trade(symbol='HAL', side='sell', quantity=10, price=32.81)
        account = self.p.repo.get_account(self.a)
        before = self.p._replay_account(account=account, as_of_date=self.day, cost_method='fifo', include_realtime=False)['public']
        self.assertAlmostEqual(before['realized_pnl'], 0.60)
        self.assertFalse(before['net_pnl_verified'])
        for tid, fee in [(buy, 1.02), (sell, 1.03)]:
            self.b.reconcile_trade(tid, dict(expected_revision=1, fee=fee, tax=0,
                fee_status='confirmed', executed_at=None, reason='Test statement'))
        after = self.p._replay_account(account=account, as_of_date=self.day, cost_method='fifo', include_realtime=False)['public']
        self.assertAlmostEqual(after['realized_pnl'], -1.45)
        self.assertEqual(self.status()['remaining_amount'], 10000)

    def test_partial_fill_reserves_only_unfilled_quantity_and_cancel_pending_does_not_release(self):
        iid = self.intent()
        self.report(iid, 'submitted')
        tid = self.trade(intent_id=iid, fee_status='confirmed', price=699, fee=1)
        self.adjustment(tid)
        s = self.status()
        self.assertEqual(s['intents'][0]['status'], 'partially_filled')
        self.assertEqual(s['reserved_amount'], 702 * 7)
        self.assertEqual(s['confirmed_spent'], 700 * 7)
        self.report(iid, 'pending_cancel', 3)
        self.assertEqual(self.status()['reserved_amount'], 702 * 7)
        self.report(iid, 'cancelled', 4)
        self.assertEqual(self.status()['reserved_amount'], 0)
        self.assertEqual(self.status()['remaining_amount'], 5100)

    def test_expired_unconfirmed_order_retains_reservation(self):
        iid = self.intent()
        self.report(iid, 'submitted')
        with self.p.repo.portfolio_write_session() as session:
            session.get(PortfolioPurchaseIntent, iid).expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        s = self.status()
        self.assertEqual(s['intents'][0]['status'], 'expired_pending_confirmation')
        self.assertEqual(s['reserved_amount'], 1402 * 7)

    def test_duplicate_fill_and_overfill_are_atomic(self):
        iid = self.intent(quantity=1)
        self.trade(intent_id=iid, trade_uid='fill-1')
        with self.assertRaises(PortfolioConflictError):
            self.trade(intent_id=iid, trade_uid='fill-1')
        with self.assertRaises(PortfolioConflictError):
            self.trade(intent_id=iid, trade_uid='fill-2')
        self.assertEqual(self.p.list_trade_events(account_id=self.a)['total'], 1)
        self.assertEqual(self.status()['intents'][0]['status'], 'filled')

    def test_reconcile_conflict_retains_audit_and_invalidates_funding(self):
        from src.services.portfolio_account_state_service import PortfolioAccountStateService
        tid = self.trade()
        funding = PortfolioAccountStateService(self.p.repo)
        funding.record_funding(self.a, dict(as_of=str(date.today()), settled_cash=1000, available_cash=1000))
        self.assertTrue(funding.get_state(self.a)['cash_confirmed'])
        data = dict(expected_revision=1, fee=1, tax=0, fee_status='confirmed', executed_at=None, reason='Statement')
        self.b.reconcile_trade(tid, data)
        self.assertFalse(funding.get_state(self.a)['cash_confirmed'])
        with self.assertRaises(PortfolioConflictError):
            self.b.reconcile_trade(tid, data)

    def test_execution_timezone_price_basis_and_nonfinite_rejected(self):
        for values in [dict(executed_at='2026-01-01T10:00:00'), dict(price=float('nan')),
                       dict(fee=float('inf')), dict(price_basis='broker_average_cost')]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.trade(**values)
        stamp = datetime.now(timezone.utc) - timedelta(minutes=1)
        tid = self.trade(executed_at=stamp, trade_date=stamp.astimezone(ZoneInfo('America/New_York')).date())
        self.assertTrue(self.p.list_trade_events(account_id=self.a)['items'][0]['executed_at'].endswith('Z'))
        self.assertGreater(tid, 0)

    def test_actual_timestamps_prevent_sell_before_buy(self):
        stamp = datetime.now(timezone.utc) - timedelta(hours=1)
        on_date = stamp.astimezone(ZoneInfo('America/New_York')).date()
        self.trade(executed_at=stamp, trade_date=on_date)
        with self.assertRaises(PortfolioOversellError):
            self.trade(side='sell', executed_at=stamp - timedelta(minutes=1), trade_date=on_date)

    def test_missing_time_on_other_symbol_does_not_change_fifo_order(self):
        # Deliberately enter the earlier lot last; an unrelated untimed trade
        # must not force this fully timestamped position back to insertion order.
        stamp = datetime.combine(self.day - timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=15)
        on_date = stamp.astimezone(ZoneInfo('America/New_York')).date()
        self.trade(symbol='VOO', trade_date=on_date)
        self.trade(symbol='HAL', quantity=10, price=20, trade_date=on_date, executed_at=stamp + timedelta(minutes=1))
        self.trade(symbol='HAL', side='sell', quantity=10, price=21, trade_date=on_date, executed_at=stamp + timedelta(minutes=2))
        self.trade(symbol='HAL', quantity=10, price=10, trade_date=on_date, executed_at=stamp)
        account = self.p.repo.get_account(self.a)
        replay = self.p._replay_account(account=account, as_of_date=self.day, cost_method='fifo', include_realtime=False)['public']
        self.assertAlmostEqual(replay['realized_pnl'], 110)

    def test_deletion_keeps_evidence_and_clears_adjustment(self):
        tid = self.trade()
        self.adjustment(tid)
        self.p.delete_trade_event(tid)
        self.assertEqual(self.status()['remaining_amount'], 10000)
        self.assertEqual(self.b.audit(self.a)[0]['action'], 'delete')

    def test_linking_existing_fill_is_idempotent_and_does_not_buy_again(self):
        tid = self.trade()
        iid = self.intent(quantity=1)
        self.b.link_existing_fill(iid, tid)
        self.b.link_existing_fill(iid, tid)
        self.assertEqual(self.p.list_trade_events(account_id=self.a)['total'], 1)
        self.assertEqual(self.status()['intents'][0]['filled_quantity'], 1)

    def test_period_budget_shared_between_targets_and_unknown_is_not_zero(self):
        plan = dict(target_total_value=100000, ledger_complete=True, targets=[
            dict(key=s, market='us', source='position', symbols=[s], target_pct=50, batch_amount=6000) for s in ['QQQM', 'VOO']])
        snapshot = dict(account_count=1, cash_value=20000, positions=[], budget_pools=[
            dict(id=1, market='us', symbols=['QQQM', 'VOO'], remaining=10000)], reserved_cash_value=2000,
            funding_complete=False)
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot=snapshot)
        self.assertEqual([t['recommended_amount'] for t in result['targets']], [6000, 4000])
        self.assertTrue(all(t['funded_amount'] is None for t in result['targets']))
        snapshot['budget_pools'][0]['remaining'] = None
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot=snapshot)
        self.assertTrue(all(t['action'] == 'review' and t['recommended_amount'] == 0 for t in result['targets']))

    def test_api_budget_evidence_and_schema_guardrails(self):
        from api.app import create_app
        from fastapi.testclient import TestClient
        client = TestClient(create_app(static_dir=Path(self.temp.name) / 'none'))
        response = client.get(f'/api/v1/portfolio/accounts/{self.a}/budgets')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'][0]['amount'], 10000)
        tid = self.trade()
        endpoint = f'/api/v1/portfolio/trades/{tid}/reconciliation'
        payload = dict(expected_revision=1, fee=1, tax=0, fee_status='confirmed', reason='Statement')
        self.assertEqual(client.put(endpoint, json=payload).status_code, 200)
        self.assertEqual(client.put(endpoint, json=payload).status_code, 409)
        self.assertEqual(client.put(endpoint, json={**payload, 'reason': ''}).status_code, 422)
        self.assertEqual(client.get(f'/api/v1/portfolio/accounts/{self.a}/audit').status_code, 200)
        body = dict(account_id=self.a, symbol='QQQM', trade_date=str(self.day), side='buy', quantity=1, price=300, request_key='manual-1')
        self.assertEqual(client.post('/api/v1/portfolio/trades', json={**body, 'fee_status': 'confirmed'}).status_code, 422)
        self.assertEqual(client.post('/api/v1/portfolio/trades', json=body).status_code, 200)
        self.assertEqual(client.post('/api/v1/portfolio/trades', json=body).status_code, 409)

    def test_budget_and_reserved_cash_reach_allocation_without_live_quotes(self):
        from src.services.portfolio_account_state_service import PortfolioAccountStateService
        from src.services.portfolio_allocation_service import PortfolioAllocationService
        aid = self.p.create_account(name='Funded', broker=None, market='us', base_currency='USD')['id']
        bid = self.b.create_budget(aid, {**self.payload, 'currency': 'USD', 'request_key': 'funded', 'amount': 500})['id']
        self.p.record_cash_ledger(account_id=aid, event_date=date.today() - timedelta(days=1), direction='in', amount=2000)
        iid = self.b.create_intent(bid, dict(symbol='QQQM', quantity=1, limit_price=100, fee_reserve=2, fx_rate=1,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), request_key='funded-intent'))['id']
        self.report(iid, 'submitted')
        PortfolioAccountStateService(self.p.repo).record_funding(aid, dict(as_of=str(date.today()), settled_cash=2000, available_cash=2000))
        allocation = PortfolioAllocationService(portfolio_service=self.p)
        plan = allocation.create_plan(name='Plan', base_currency='USD', target_total_value=2000,
            account_id=aid, ledger_complete=True, targets=[dict(key=s.lower(), name=s, source='position', policy='buy_only',
                market='us', symbols=[s], target_pct=50, batch_amount=1000) for s in ['QQQM', 'VOO']])
        result = allocation.evaluate_plan(plan['id'], include_realtime=False)
        self.assertEqual(result['available_cash'], 1898)
        self.assertEqual(sum(t['recommended_amount'] for t in result['targets']), 398)
        self.assertEqual(sum(t['funded_amount'] for t in result['targets']), 398)

    def test_reinitialization_preserves_unknown_historical_fees(self):
        tid = self.trade()
        DatabaseManager.reset_instance()
        self.p = PortfolioService()
        row = self.p.list_trade_events(account_id=self.a)['items'][0]
        self.assertEqual((row['id'], row['fee_status'], row['executed_at']), (tid, 'unknown', None))

    def test_legacy_schema_upgrade_keeps_trade_values_and_is_repeatable(self):
        legacy_path = Path(self.temp.name) / 'legacy.db'
        with sqlite3.connect(legacy_path) as connection:
            connection.execute('''CREATE TABLE portfolio_trades (
                id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, trade_uid VARCHAR(128),
                symbol VARCHAR(16) NOT NULL, market VARCHAR(8) NOT NULL, currency VARCHAR(8) NOT NULL,
                trade_date DATE NOT NULL, side VARCHAR(8) NOT NULL, quantity FLOAT NOT NULL,
                price FLOAT NOT NULL, fee FLOAT, tax FLOAT, note VARCHAR(255),
                dedup_hash VARCHAR(64), created_at DATETIME)''')
            connection.execute('''INSERT INTO portfolio_trades
                (id, account_id, symbol, market, currency, trade_date, side, quantity, price, fee, tax)
                VALUES (1, 1, 'VOO', 'us', 'USD', ?, 'buy', 1, 707.63, 0, 0)''', (str(self.day),))
        with patch.dict(os.environ, {'DATABASE_PATH': str(legacy_path)}):
            for _ in range(2):
                Config.reset_instance()
                DatabaseManager.reset_instance()
                service = PortfolioService()
                rows = service.repo.list_trades(1, self.day)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual((row.quantity, row.price, row.fee, row.tax), (1, 707.63, 0, 0))
                self.assertEqual((row.fee_status, row.executed_at, row.revision, row.intent_id),
                                 ('unknown', None, 1, None))
