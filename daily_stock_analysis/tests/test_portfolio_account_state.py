"""Opening balance integration and funding safety, with a real temporary ledger."""
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from src.config import Config
from src.storage import DatabaseManager
from src.services.portfolio_service import PortfolioService, PortfolioConflictError, PortfolioOversellError
from src.services.portfolio_account_state_service import PortfolioAccountStateService
from src.services.portfolio_allocation_service import PortfolioAllocationService


class AccountStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ['DATABASE_PATH'] = str(Path(self.temp.name) / 'test.db')
        os.environ['ENV_FILE'] = str(Path(self.temp.name) / '.env')
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.portfolio = PortfolioService()
        self.state = PortfolioAccountStateService(self.portfolio.repo)
        self.aid = self.portfolio.create_account(name='Test', broker='Test', market='us', base_currency='USD')['id']
        self.day = date.today() - timedelta(days=2)
        self.payload = dict(as_of=self.day.isoformat(), cash_balance=None,
                            reported_market_value=8217, reported_equity=9731,
                            positions=[dict(symbol=s, quantity=q, avg_cost=c, reported_market_value=v)
                                       for s, q, c, v in [('EUV', 105, 29.46, 2618), ('DRAM', 24, 64.37, 1488),
                                                          ('QQQM', 11, 293.746, 3374), ('VOO', 1, 707.63, 711.35)]])

    def tearDown(self):
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.clear()
        os.environ.update(self.env)
        self.temp.cleanup()

    def commit(self, cash=1514):
        self.payload['cash_balance'] = cash
        preview = self.state.preview_opening(self.aid, self.payload)
        return self.state.commit_opening(self.aid, self.payload, preview['preview_token'])

    def snapshot(self, method='fifo'):
        for item in self.payload['positions']:
            self.db.save_daily_data(pd.DataFrame([dict(date=date.today(), open=30, high=30, low=30,
                                                       close=30, volume=1, amount=30, pct_chg=0)]),
                                    code=item['symbol'], data_source='test')
        self.portfolio.repo.save_fx_rate(rate_date=date.today(), from_currency='USD', to_currency='CNY',
                                        rate=7, source='test')
        return self.portfolio.get_portfolio_snapshot(account_id=self.aid, include_realtime=False,
                                                     cost_method=method)['accounts'][0]

    def test_unknown_cash_preview_is_read_only_and_does_not_infer_cash(self):
        preview = self.state.preview_opening(self.aid, self.payload)
        self.assertAlmostEqual(preview['market_value_difference'], 25.65)
        self.assertEqual(preview['equity_less_market_value'], 1514)
        self.assertIsNone(preview['opening']['cash_balance'])
        self.assertFalse(preview['can_commit'])
        self.assertIsNone(self.portfolio.repo.get_opening_balance(self.aid))
        with self.assertRaises(ValueError):
            self.state.commit_opening(self.aid, self.payload, preview['preview_token'])

    def test_commit_idempotent_replay_no_fake_trades_or_deposits(self):
        self.assertTrue(self.commit()['created'])
        self.assertFalse(self.commit()['created'])
        self.assertEqual(self.portfolio.repo.list_trades(self.aid, date.today()), [])
        self.assertEqual(self.portfolio.repo.list_cash_ledger(self.aid, date.today()), [])
        for method in ('fifo', 'avg'):
            result = self.snapshot(method)
            self.assertEqual({x['symbol']: x['quantity'] for x in result['positions']},
                             {'EUV': 105, 'DRAM': 24, 'QQQM': 11, 'VOO': 1})
            self.assertEqual(result['total_cash'], 1514)
            self.assertEqual(result['realized_pnl'], 0)
            self.assertIn('historical_realized_pnl_unavailable', result['limitations'])
            self.assertIsNone(result['funding']['confirmed_cash_cap'])

    def test_changed_preview_and_overwrite_rejected(self):
        self.payload['cash_balance'] = 1514
        preview = self.state.preview_opening(self.aid, self.payload)
        self.payload['positions'][0]['quantity'] = 106
        with self.assertRaises(PortfolioConflictError):
            self.state.commit_opening(self.aid, self.payload, preview['preview_token'])
        self.commit()
        self.payload['positions'][0]['quantity'] = 107
        with self.assertRaises(PortfolioConflictError):
            self.commit()

    def test_preexisting_events_reject_opening(self):
        self.portfolio.record_cash_ledger(account_id=self.aid, event_date=self.day, direction='in', amount=1)
        with self.assertRaises(PortfolioConflictError):
            self.commit()

    def test_boundary_blocks_all_old_event_types_and_allows_later_sell(self):
        self.commit()
        for event_date in (self.day - timedelta(days=1), self.day):
            with self.assertRaises(ValueError):
                self.portfolio.record_trade(account_id=self.aid, symbol='EUV', trade_date=event_date,
                                             side='buy', quantity=15, price=26.8)
            with self.assertRaises(ValueError):
                self.portfolio.record_cash_ledger(account_id=self.aid, event_date=event_date, direction='in', amount=1)
            with self.assertRaises(ValueError):
                self.portfolio.record_corporate_action(account_id=self.aid, symbol='EUV', effective_date=event_date,
                                                       action_type='split_adjustment', split_ratio=2)
        self.portfolio.record_trade(account_id=self.aid, symbol='EUV', trade_date=self.day + timedelta(days=1),
                                     side='sell', quantity=20, price=30, fee=1.06)
        for method in ('fifo', 'avg'):
            result = self.snapshot(method)
            self.assertEqual(next(x['quantity'] for x in result['positions'] if x['symbol'] == 'EUV'), 85)
            self.assertAlmostEqual(result['total_cash'], 2112.94)
            self.assertAlmostEqual(result['realized_pnl'], 9.74)
        with self.assertRaises(PortfolioOversellError):
            self.portfolio.record_trade(account_id=self.aid, symbol='EUV', trade_date=date.today(),
                                         side='sell', quantity=86, price=30)

    def test_funding_never_creates_deposit_and_expires_after_event(self):
        self.commit()
        self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), settled_cash=1000,
                                                 available_cash=900, planned_deposit=30000))
        self.assertEqual(self.state.get_state(self.aid)['confirmed_cash_cap'], 900)
        self.assertEqual(self.snapshot()['total_cash'], 1514)
        self.portfolio.record_cash_ledger(account_id=self.aid, event_date=date.today(), direction='in', amount=5)
        result = self.state.get_state(self.aid)
        self.assertFalse(result['cash_confirmed'])
        self.assertEqual(result['funding']['planned_deposit'], 30000)
        self.assertIsNone(self.state.get_state(self.aid, date.today() + timedelta(days=1))['confirmed_cash_cap'])

    def test_funding_date_unknown_and_numeric_validation(self):
        self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), planned_deposit=30000))
        self.assertIsNone(self.state.get_state(self.aid)['confirmed_cash_cap'])
        with self.assertRaises(ValueError):
            self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), settled_cash=float('nan')))
        with self.assertRaises(ValueError):
            self.state.record_funding(self.aid, dict(as_of=(date.today() + timedelta(days=1)).isoformat()))

    def test_funding_cap_integration_does_not_exceed_ledger_or_cross_market(self):
        self.commit()
        self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), settled_cash=99999,
                                                 available_cash=99999, planned_deposit=30000))
        account = self.snapshot()
        allocation = PortfolioAllocationService(portfolio_service=self.portfolio)
        normalized = allocation._normalize_snapshot(snapshot={'accounts': [account], 'account_count': 1},
                                                     plan_currency='USD', as_of_date=date.today())
        self.assertEqual(normalized['confirmed_pools'], {'us': 1514})
        from src.core.portfolio_allocation import evaluate_allocation_plan
        plan = dict(target_total_value=100000, ledger_complete=True, targets=[
            dict(key='one', source='position', policy='buy_only', symbols=['QQQM'], market='us', target_pct=50),
            dict(key='two', source='position', policy='buy_only', symbols=['VOO'], market='us', target_pct=40),
            dict(key='cn', source='position', policy='buy_only', symbols=['510580'], market='cn', target_pct=10)])
        # This test isolates funding allocation from holiday quote qualification.
        for p in normalized['positions']:
            p.update(price_stale=False, fx_stale=False)
        result = evaluate_allocation_plan(plan=plan, normalized_snapshot=normalized)
        self.assertEqual(result['confirmed_cash'], 1514)
        self.assertLessEqual(sum(x['funded_amount'] or 0 for x in result['targets']), 1514)
        self.assertIsNone(result['targets'][2]['funded_amount'])

    def test_api_preview_confirmation_validation_and_state(self):
        from fastapi import FastAPI
        from api.v1.endpoints.portfolio import router
        app = FastAPI()
        app.include_router(router, prefix='/portfolio')
        client = TestClient(app)
        url = f'/portfolio/accounts/{self.aid}'
        self.payload['cash_balance'] = 1514
        response = client.post(url + '/opening-balance/preview', json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()['preview_token']
        body = dict(**self.payload, preview_token=token)
        self.assertEqual(client.post(url + '/opening-balance', json=body).status_code, 422)
        body['confirmed'] = True
        self.assertEqual(client.post(url + '/opening-balance', json=body).status_code, 200)
        self.assertFalse(client.post(url + '/opening-balance', json=body).json()['created'])
        self.assertEqual(client.get(url + '/state').json()['opening']['positions'][0]['symbol'], 'DRAM')

    def test_opening_cannot_change_currency_or_read_prebaseline_history(self):
        self.commit()
        with self.assertRaises(ValueError):
            self.portfolio.update_account(self.aid, base_currency='CNY')
        with self.assertRaises(ValueError):
            self.portfolio.get_portfolio_snapshot(account_id=self.aid, as_of=self.day - timedelta(days=1))

    def test_concurrent_opening_confirmation_creates_one_baseline(self):
        from concurrent.futures import ThreadPoolExecutor
        self.payload['cash_balance'] = 1514
        token = self.state.preview_opening(self.aid, self.payload)['preview_token']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.state.commit_opening(self.aid, self.payload, token), range(2)))
        self.assertEqual(sum(result['created'] for result in results), 1)
        self.assertEqual(next(p['quantity'] for p in self.snapshot()['positions'] if p['symbol'] == 'EUV'), 105)

    def test_baseline_split_is_replayed_and_repository_prevents_backdated_import(self):
        self.commit()
        self.portfolio.record_corporate_action(account_id=self.aid, symbol='EUV',
                                               effective_date=self.day + timedelta(days=1),
                                               action_type='split_adjustment', split_ratio=2)
        for method in ('fifo', 'avg'):
            result = next(p for p in self.snapshot(method)['positions'] if p['symbol'] == 'EUV')
            self.assertEqual(result['quantity'], 210)
            self.assertAlmostEqual(result['avg_cost'], 14.73)
        from src.services.portfolio_import_service import PortfolioImportService
        importer = PortfolioImportService(portfolio_service=self.portfolio, repo=self.portfolio.repo)
        records = [dict(symbol='EUV', trade_date=self.day.isoformat(), side='buy', quantity=15, price=26.8)]
        for dry_run in (True, False):
            result = importer.commit_trade_records(account_id=self.aid, broker='huatai', records=records, dry_run=dry_run)
            self.assertEqual(result['inserted_count'], 0)
            self.assertEqual(result['failed_count'], 1)
        self.assertEqual(self.portfolio.repo.list_trades(self.aid, date.today()), [])
        with self.assertRaises(ValueError):
            self.portfolio.repo.update_account(self.aid, {'market': 'cn'})

    def test_ledger_change_during_snapshot_invalidates_funding(self):
        from unittest.mock import patch
        self.commit()
        self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), settled_cash=1514, available_cash=1514))
        original = self.portfolio.repo.list_cash_ledger

        def concurrent_change(*args, **kwargs):
            self.portfolio.record_cash_ledger(account_id=self.aid, event_date=date.today(), direction='in', amount=1)
            self.state.record_funding(self.aid, dict(as_of=date.today().isoformat(), settled_cash=1515, available_cash=1515))
            return original(*args, **kwargs)

        with patch.object(self.portfolio.repo, 'list_cash_ledger', side_effect=concurrent_change):
            result = self.snapshot()
        self.assertIsNone(result['funding']['confirmed_cash_cap'])
        self.assertIn('ledger_changed_during_snapshot', result['limitations'])
