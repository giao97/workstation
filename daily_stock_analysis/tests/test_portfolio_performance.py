"""Deterministic reviews of actual temporary ledgers, without brokerage orders."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.config import Config
from src.core.portfolio_performance import aggregate_contributions
from src.services.portfolio_budget_service import PortfolioBudgetService
from src.services.portfolio_performance_service import PortfolioPerformanceService
from src.services.portfolio_service import PortfolioService, _ResolvedPositionPrice
from src.storage import DatabaseManager


class PortfolioPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ENV_FILE': str(Path(self.temp.name) / 'empty.env'),
                                         'DATABASE_PATH': str(Path(self.temp.name) / 'ledger.db')})
        self.env.start()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.p = PortfolioService()
        self.service = PortfolioPerformanceService(self.p.repo)
        self.a = self.p.create_account(name='Review', broker=None, market='us', base_currency='USD')['id']
        self.now = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
        self.day = self.now.astimezone(ZoneInfo('America/New_York')).date()
        self.clock = patch('src.services.portfolio_performance_service.datetime', wraps=datetime)
        self.mock_clock = self.clock.start()
        self.mock_clock.now.return_value = self.now
        # An accidental quote request must fail locally, never escape to a provider.
        self.quote = patch.object(PortfolioService, '_fetch_realtime_position_price', return_value=None)
        self.mock_quote = self.quote.start()

    def tearDown(self):
        self.quote.stop()
        self.clock.stop()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.env.stop()
        self.temp.cleanup()

    def trade(self, **kwargs):
        fields = dict(account_id=self.a, symbol='EUV', trade_date=self.day, side='buy',
                      quantity=20, price=29, fee=1.05, tax=0, fee_status='confirmed')
        fields.update(kwargs)
        return self.p.record_trade(**fields)['id']

    def baseline(self, **kwargs):
        return self.trade(quantity=105, price=29.46, trade_date=self.day - timedelta(days=1),
                          fee_status='unknown', **kwargs)

    def evaluate(self, **kwargs):
        return self.service.evaluate(self.a, **dict(start_date=self.day, end_date=self.day,
                                    ledger_confirmed=True, **kwargs))

    def fresh_quote(self, price=32, **kwargs):
        fields = dict(price=price, source='realtime_quote', provider='test-provider', price_date=self.day,
                      timestamp=self.now.isoformat(), fetched_at=self.now.isoformat(),
                      is_available=True, is_stale=False)
        fields.update(kwargs)
        self.mock_quote.return_value = _ResolvedPositionPrice(**fields)

    def test_closed_euv_uses_original_105_shares_and_does_not_fetch_quotes(self):
        self.baseline()
        self.trade(side='sell', price=30, fee=1.06)
        self.trade()
        result = self.evaluate()
        row = result['items'][0]
        self.assertEqual((row['status'], row['baseline_quantity'], row['ending_quantity']), ('restored', 105, 105))
        self.assertAlmostEqual(row['closed_net_pnl'], 17.89)
        self.assertAlmostEqual(row['relative_hold_pnl'], 17.89)
        self.assertAlmostEqual(row['economic_cost_improvement_per_share'], 17.89 / 105)
        self.assertEqual(row['comparison_kind'], 'cash_difference')
        self.assertIn('performance_execution_time_unknown', row['limitations'])
        self.mock_quote.assert_not_called()

    def test_hal_zero_baseline_is_cash_comparison_not_other_holdings_cost_reduction(self):
        self.trade(symbol='HAL', quantity=10, price=32.75, fee=1.02)
        self.trade(symbol='HAL', side='sell', quantity=10, price=32.81, fee=1.03)
        row = self.evaluate()['items'][0]
        self.assertAlmostEqual(row['gross_cash_flow'], .60)
        self.assertAlmostEqual(row['closed_net_pnl'], -1.45)
        self.assertEqual(row['baseline_kind'], 'unchanged_cash')
        self.assertIsNone(row['economic_cost_improvement_per_share'])
        self.assertAlmostEqual(row['relative_hold_pnl'], -1.45)

    def test_unknown_or_estimated_costs_do_not_become_net_profit(self):
        buy = self.trade(symbol='HAL', quantity=10, price=32.75, fee=0, fee_status='unknown')
        self.trade(symbol='HAL', side='sell', quantity=10, price=32.81, fee=1.03)
        for status in ('unknown', 'estimated'):
            if status == 'estimated':
                PortfolioBudgetService(self.p.repo).reconcile_trade(buy, dict(expected_revision=1, fee=1.02,
                    tax=0, fee_status=status, reason='Estimate only', executed_at=None))
            row = self.evaluate()['items'][0]
            self.assertAlmostEqual(row['gross_cash_flow'], .60)
            self.assertIsNone(row['closed_net_pnl'])
            self.assertIsNone(row['relative_hold_pnl'])
            self.assertEqual(row['unverified_fee_trade_ids'], [buy])

    def test_incomplete_ledger_blocks_verified_comparison_even_with_confirmed_costs(self):
        self.trade(symbol='HAL', quantity=10, price=32.75)
        self.trade(symbol='HAL', side='sell', quantity=10, price=32.81)
        report = self.service.evaluate(self.a, start_date=self.day, end_date=self.day)
        self.assertIsNone(report['items'][0]['closed_net_pnl'])
        self.assertIsNone(report['totals_by_currency'][0]['relative_hold_pnl'])
        self.assertIn('performance_ledger_unconfirmed', report['items'][0]['limitations'])

    def test_partial_rebuy_is_not_completed_and_accounts_for_sold_away_upside(self):
        self.baseline()
        stamp = self.now - timedelta(minutes=1)
        self.trade(side='sell', price=30, fee=1.06, executed_at=stamp)
        self.trade(quantity=10, executed_at=stamp + timedelta(seconds=10))
        self.fresh_quote(price=32)
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertEqual((row['ending_quantity'], row['unrecovered_quantity']), (95, 10))
        self.assertAlmostEqual(row['net_cash_flow'], 307.89)
        self.assertAlmostEqual(row['relative_hold_pnl'], -12.11)
        self.assertEqual(row['comparison_kind'], 'marked_estimate')
        self.assertIsNone(row['closed_net_pnl'])
        self.assertIsNone(row['economic_cost_improvement_per_share'])

    def test_regular_voo_addition_is_not_a_closed_trading_profit(self):
        self.trade(symbol='VOO', quantity=1, price=707.63, trade_date=self.day - timedelta(days=1))
        self.trade(symbol='VOO', quantity=1, price=702.89, fee=1.04, executed_at=self.now - timedelta(minutes=1))
        self.fresh_quote(price=711)
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertEqual((row['status'], row['extra_quantity']), ('over_baseline', 1))
        self.assertIsNone(row['closed_net_pnl'])
        self.assertIsNone(row['economic_cost_improvement_per_share'])
        self.assertAlmostEqual(row['relative_hold_pnl'], 7.07)

    def test_stale_future_missing_provider_and_pre_execution_quotes_are_not_used(self):
        self.baseline()
        self.trade(side='sell', price=30, executed_at=self.now - timedelta(seconds=10))
        for patch_values in [dict(timestamp=(self.now - timedelta(minutes=6)).isoformat()),
                             dict(timestamp=(self.now + timedelta(seconds=1)).isoformat()),
                             dict(provider=None), dict(timestamp=None), dict(is_stale=True),
                             dict(price=float('nan')), dict(price=0),
                             dict(timestamp=(self.now - timedelta(seconds=20)).isoformat())]:
            with self.subTest(patch_values=patch_values):
                self.fresh_quote(**patch_values)
                row = self.evaluate(include_realtime=True)['items'][0]
                self.assertFalse(row['valuation']['usable'])
                self.assertIsNone(row['relative_hold_pnl'])
                self.assertIsNone(row['closed_net_pnl'])

    def test_untimed_current_day_fill_blocks_mark_but_not_closed_cash_arithmetic(self):
        self.baseline()
        self.trade(side='sell', price=30)
        self.fresh_quote()
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertEqual(row['valuation']['reason'], 'intraday_execution_time_unknown')
        self.assertIsNone(row['relative_hold_pnl'])

    def test_us_exchange_date_used_instead_of_beijing_midnight(self):
        self.mock_clock.now.return_value = self.now.replace(hour=23, minute=30)
        self.baseline()
        self.trade(side='sell', executed_at=self.now)
        self.fresh_quote(timestamp=self.mock_clock.now.return_value.isoformat())
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertTrue(row['valuation']['usable'])

    def test_historical_open_window_does_not_use_current_or_adjusted_daily_price(self):
        self.baseline()
        self.trade(side='sell')
        self.mock_clock.now.return_value = self.now + timedelta(days=1)
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertEqual(row['valuation']['reason'], 'historical_unadjusted_endpoint_unavailable')
        self.assertIsNone(row['relative_hold_pnl'])
        self.mock_quote.assert_not_called()

    def test_losing_round_trip_is_included_and_can_increase_economic_cost(self):
        self.baseline()
        self.trade(side='sell', price=30, fee=1)
        self.trade(price=31, fee=1)
        row = self.evaluate()['items'][0]
        self.assertEqual(row['closed_net_pnl'], -22)
        self.assertAlmostEqual(row['economic_cost_improvement_per_share'], -22 / 105)

    def test_multiple_cycles_all_count_not_only_the_winners(self):
        self.baseline()
        for sell, buy in [(30, 29), (29, 31)]:
            self.trade(side='sell', price=sell, fee=1)
            self.trade(price=buy, fee=1)
        row = self.evaluate()['items'][0]
        self.assertEqual(row['trade_count'], 4)
        self.assertEqual(row['closed_net_pnl'], -24)

    def test_dividends_and_splits_block_unsupported_benchmark(self):
        self.baseline()
        self.trade(side='sell', price=30)
        self.trade()
        self.p.record_corporate_action(account_id=self.a, symbol='EUV', effective_date=self.day,
            action_type='cash_dividend', cash_dividend_per_share=1)
        row = self.evaluate()['items'][0]
        self.assertEqual(row['status'], 'unsupported')
        self.assertIsNone(row['relative_hold_pnl'])
        self.assertIsNone(row['economic_cost_improvement_per_share'])
        self.assertIsNone(row['share_gap'])

    def test_split_is_not_misreported_as_added_trading_shares(self):
        self.baseline()
        self.p.record_corporate_action(account_id=self.a, symbol='EUV', effective_date=self.day,
            action_type='split_adjustment', split_ratio=2)
        row = self.evaluate()['items'][0]
        self.assertEqual((row['baseline_quantity'], row['ending_quantity']), (105, 210))
        self.assertEqual(row['status'], 'unsupported')
        self.assertIsNone(row['extra_quantity'])
        self.assertIsNone(row['relative_hold_pnl'])

    def test_cash_deposits_do_not_become_trading_profit(self):
        self.baseline()
        self.trade(side='sell', price=30, fee=1.06)
        self.trade()
        self.p.record_cash_ledger(account_id=self.a, event_date=self.day, direction='in', amount=10000)
        row = self.evaluate()['items'][0]
        self.assertAlmostEqual(row['closed_net_pnl'], 17.89)

    def test_opening_inventory_is_reused_without_fabricated_historical_buys(self):
        from src.services.portfolio_account_state_service import PortfolioAccountStateService
        states = PortfolioAccountStateService(self.p.repo)
        opening = dict(as_of=str(self.day - timedelta(days=1)), cash_balance=0,
                       positions=[dict(symbol='EUV', quantity=105, avg_cost=29.46)])
        preview = states.preview_opening(self.a, opening)
        states.commit_opening(self.a, opening, preview['preview_token'])
        self.trade(side='sell', price=30, fee=1.06)
        self.trade()
        row = self.evaluate()['items'][0]
        self.assertEqual((row['baseline_quantity'], row['ending_quantity']), (105, 105))
        self.assertAlmostEqual(row['economic_cost_improvement_per_share'], 17.89 / 105)
        self.assertEqual(self.p.list_trade_events(account_id=self.a)['total'], 2)
        with self.assertRaisesRegex(ValueError, 'after the confirmed'):
            self.service.evaluate(self.a, start_date=self.day - timedelta(days=1), end_date=self.day)

    def test_non_native_currency_is_not_marked_with_a_native_price(self):
        self.trade(symbol='VOO', currency='CNY', quantity=1, price=4900,
                   executed_at=self.now - timedelta(minutes=1))
        self.fresh_quote(price=700)
        row = self.evaluate(include_realtime=True)['items'][0]
        self.assertIsNone(row['relative_hold_pnl'])
        self.assertEqual(row['valuation']['reason'], 'valuation_currency_mismatch')
        self.mock_quote.assert_not_called()

    def test_inactive_period_holding_reports_zero_contribution_not_a_winning_cycle(self):
        self.baseline()
        row = self.evaluate(symbols=['EUV'])['items'][0]
        self.assertEqual(row['status'], 'no_activity')
        self.assertEqual(row['relative_hold_pnl'], 0)
        self.assertIsNone(row['closed_net_pnl'])
        self.assertIsNone(row['economic_cost_improvement_per_share'])

    def test_fractional_restoration_is_not_left_open_by_float_replay_dust(self):
        self.trade(quantity=.3, trade_date=self.day - timedelta(days=1))
        self.trade(quantity=.1, price=29, fee=0)
        self.trade(side='sell', quantity=.1, price=30, fee=0)
        row = self.evaluate()['items'][0]
        self.assertEqual((row['status'], row['baseline_quantity'], row['ending_quantity']), ('restored', .3, .3))
        self.assertAlmostEqual(row['closed_net_pnl'], .1)
        self.mock_quote.assert_not_called()

    def test_review_is_read_only_and_reconciled_fees_change_evidence(self):
        buy = self.trade(symbol='HAL', quantity=10, price=32.75, fee_status='unknown')
        self.trade(symbol='HAL', side='sell', quantity=10, price=32.81)
        fingerprint = self.p.repo.ledger_fingerprint(self.a)
        first = self.evaluate()
        self.assertEqual(fingerprint, self.p.repo.ledger_fingerprint(self.a))
        self.assertEqual(PortfolioBudgetService(self.p.repo).audit(self.a), [])
        PortfolioBudgetService(self.p.repo).reconcile_trade(buy, dict(expected_revision=1, fee=1.02, tax=0,
            fee_status='confirmed', reason='Test statement', executed_at=None))
        second = self.evaluate()
        self.assertNotEqual(first['ledger_fingerprint'], second['ledger_fingerprint'])
        self.assertNotEqual(first['evidence_hash'], second['evidence_hash'])
        self.assertIsNotNone(second['items'][0]['closed_net_pnl'])

    def test_date_scope_and_unrecorded_symbol_guardrails(self):
        self.baseline()
        for fields in [dict(start_date=self.day + timedelta(days=1), end_date=self.day),
                       dict(start_date=self.day, end_date=self.day + timedelta(days=1)),
                       dict(start_date=self.day - timedelta(days=367), end_date=self.day),
                       dict(start_date=self.day, end_date=self.day, symbols=['512890'])]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.service.evaluate(self.a, **fields)

    def test_currency_totals_never_mix_or_silently_drop_unknowns(self):
        totals = aggregate_contributions([
            dict(currency='USD', relative_hold_pnl=10, closed_net_pnl=10, comparison_kind='cash_difference'),
            dict(currency='USD', relative_hold_pnl=None, closed_net_pnl=None, comparison_kind='unavailable'),
            dict(currency='CNY', relative_hold_pnl=-2, closed_net_pnl=-2, comparison_kind='cash_difference'),
        ])
        usd = next(t for t in totals if t['currency'] == 'USD')
        self.assertIsNone(usd['relative_hold_pnl'])
        self.assertEqual((usd['verified_closed_net_pnl'], usd['closed_verified_count'], usd['item_count']), (10, 1, 2))
        self.assertEqual(next(t for t in totals if t['currency'] == 'CNY')['relative_hold_pnl'], -2)

    def test_api_returns_review_with_no_new_events_and_requires_valid_scope(self):
        from api.app import create_app
        from fastapi.testclient import TestClient
        client = TestClient(create_app(static_dir=Path(self.temp.name) / 'none'))
        self.trade(symbol='HAL', quantity=10, price=32.75, fee=1.02)
        self.trade(symbol='HAL', side='sell', quantity=10, price=32.81, fee=1.03)
        endpoint = f'/api/v1/portfolio/accounts/{self.a}/performance-review'
        body = dict(start_date=str(self.day), end_date=str(self.day), symbols=['HAL'], ledger_confirmed=True)
        response = client.post(endpoint, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['items'][0]['closed_net_pnl'], -1.45)
        self.assertEqual(self.p.list_trade_events(account_id=self.a)['total'], 2)
        self.assertEqual(client.post(endpoint, json={**body, 'start_date': 'bad'}).status_code, 422)
        self.assertEqual(client.post(endpoint, json={**body, 'symbols': ['FAKE']}).status_code, 400)
