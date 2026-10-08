"""Offline fixtures: price research cannot mutate the ledger or trade budgets."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from src.core.core_entry import assess_core_entry
from src.services.core_entry_service import CoreEntryService


def series(prices=None):
    prices = prices if prices is not None else [100] * 58 + [94, 95]
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(len(prices))]
    return [dict(date=d, close=p, source='SyntheticFixture') for d, p in zip(dates, prices)], dates


def test_pullback_candidate_independent_of_cost_and_no_execution():
    bars, dates = series()
    result = assess_core_entry('QQQM', bars, dates, cost=90)
    assert result['state'] == 'candidate'
    assert result['metrics']['drawdown_pct'] == -5
    assert result['metrics']['ledger_cost'] == 90
    assert result['metrics']['low60'] == 94
    assert not result['executable']
    assert 'quantity' not in result and 'amount' not in result
    assert assess_core_entry('VOO', bars, dates)['state'] == 'candidate'


def test_cost_or_flat_window_low_alone_never_triggers():
    bars, dates = series([100] * 60)
    result = assess_core_entry('QQQM', bars, dates, cost=110)
    assert result['state'] == 'wait'
    assert result['checks'] == ['below_cost_context_only']


def test_declining_close_waits_and_deep_drop_requests_risk_review():
    bars, dates = series([100] * 58 + [96, 95])
    assert assess_core_entry('QQQM', bars, dates)['reasons'] == ['wait_for_stabilization']
    for prices in ([100] * 58 + [79, 80], [100] * 58 + [99, 92], [50] * 10 + [100] * 48 + [94, 95]):
        bars, dates = series(prices)
        assert assess_core_entry('VOO', bars, dates)['state'] == 'risk_review'


@pytest.mark.parametrize('bad', [None, 0, -1, float('nan'), float('inf'), True])
def test_invalid_prices_never_become_opportunity(bad):
    bars, dates = series()
    bars[0]['close'] = bad
    assert assess_core_entry('QQQM', bars, dates)['state'] == 'data_required'


def test_history_must_match_completed_sessions_and_single_source():
    bars, dates = series()
    for invalid in [bars[:-1], bars[1:], bars[::-1], bars + [bars[-1]]]:
        assert assess_core_entry('QQQM', invalid, dates)['state'] == 'data_required'
    for source in ['', 'OtherFixture']:
        bars[0]['source'] = source
        assert assess_core_entry('QQQM', bars, dates)['reasons'] == ['source_missing_or_mixed']
    assert assess_core_entry('QQQM', bars, [])['reasons'] == ['calendar_unavailable']
    assert assess_core_entry('EUV', bars, dates)['state'] == 'data_required'


def test_real_calendar_uses_previous_close_during_session_without_budget_changes():
    # Monday 10:00 ET, during the session; weekend and current partial bar excluded.
    now = datetime(2026, 10, 5, 14, tzinfo=timezone.utc)
    from src.core import trading_calendar as calendar
    cal = calendar.xcals.get_calendar('XNYS')
    dates = [s.date() for s in cal.sessions_in_range(date(2026, 5, 1), date(2026, 10, 2))[-60:]]
    assert len(dates) == 60
    bars, _ = series()
    for bar, day in zip(bars, dates):
        bar['date'] = day
    repo = Mock()
    repo.core_entry_daily_bars.return_value = bars
    service = CoreEntryService(repo, clock=lambda: now)
    targets = [dict(key=s, source='position', market='us', symbols=[s], action='add',
                    recommended_amount=100, funded_amount=None) for s in ['QQQM', 'VOO', 'EUV']]
    result = dict(targets=targets, total_recommended_add=300)
    original = deepcopy(result)
    snapshot = dict(accounts=[dict(positions=[dict(symbol='QQQM', market='us', currency='USD', quantity=12, avg_cost=90)])])
    service.annotate(result, snapshot)
    for before, target in zip(original['targets'], result['targets']):
        assert all(target[k] == v for k, v in before.items())
    entry = result['targets'][0]['core_entries'][0]
    assert entry['state'] == 'candidate' and entry['allocation_ready'] is False
    assert entry['as_of'] == '2026-10-02' and entry['metrics']['ledger_cost'] == 90
    assert result['targets'][2]['core_entries'] == []
    assert result['total_recommended_add'] == 300
    repo.core_entry_daily_bars.assert_any_call('QQQM', dates[0], dates[-1])
    from api.v1.schemas.portfolio import CoreEntryAssessment
    assert CoreEntryAssessment.model_validate(entry).executable is False


def test_sqlite_repository_filters_future_and_preserves_source(tmp_path, monkeypatch):
    from src.storage import DatabaseManager, StockDaily
    from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
    monkeypatch.setenv('ENV_FILE', str(tmp_path / 'missing.env'))
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f'sqlite:///{tmp_path / "entry.db"}')
    try:
        with db.get_session() as session:
            session.add_all([StockDaily(code='QQQM', date=date(2026, 10, d), close=100, data_source='Fixture') for d in [1, 2, 5]])
            session.commit()
        bars = PortfolioAllocationRepository(db).core_entry_daily_bars('QQQM', date(2026, 10, 1), date(2026, 10, 2))
        assert [b['date'].day for b in bars] == [1, 2]
        assert bars[0]['source'] == 'Fixture'
    finally:
        DatabaseManager.reset_instance()


def test_report_exposes_research_not_execution_and_sanitizes_source():
    from src.core.portfolio_allocation import evaluate_allocation_plan
    from src.services.portfolio_allocation_report import render_allocation_status
    status = evaluate_allocation_plan(plan=dict(id=1, name='Fixture', version=1, base_currency='USD',
        ledger_complete=True, target_total_value=10000, cash_reserve_amount=0,
        targets=[dict(key='core', name='QQQM', source='position', market='us', symbols=['QQQM'],
                      target_pct=100, policy='buy_only', batch_amount=1000)]),
        normalized_snapshot=dict(account_count=1, as_of='2026-10-02', cash_value=2000, positions=[]))
    bars, dates = series()
    entry = assess_core_entry('QQQM', bars, dates)
    entry['sources'] = ['<script>invalid</script>']
    status['targets'][0]['core_entries'] = [entry]
    zh, en = render_allocation_status(status), render_allocation_status(status, language='en')
    assert '回撤候选，待综合复核' in zh and '不设固定买入日' in zh
    assert 'No fixed purchase dates' in en and 'core-pullback-v1' in en
    assert '<script>' not in zh
