from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.schemas.tactical_research import TacticalPreviewRequest
from src.core.tactical_research import preview_tactical

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def request(**patch):
    return TacticalPreviewRequest(**{
        'available_cash_usd': 2033, 'cash_as_of': NOW, 'cash_net_of_other_budgets': True,
        'loss_tolerance_pct': 40, 'lots': [dict(symbol='EUV', investment_usd=500,
            planned_loss_pct=5, round_trip_cost_usd=3, thesis='Hypothetical confirmed trend',
            invalidation='Hypothetical trend invalidation')], **patch})


def test_separate_new_lot_denominator_no_target_or_cost_basis_gate():
    result = preview_tactical(request(), NOW)
    assert result['state'] == 'scenario_only' and result['executable'] is False
    assert result['tolerance_usd'] == 200  # 40% of NEW 500, not cash or old EUV shares
    assert result['planned_loss_usd'] == 28 and result['cash_required_usd'] == 503
    assert result['remaining_cash_usd'] == 1530


def test_shared_cash_counts_all_lots_and_both_sides_costs():
    lots = [request().lots[0].model_dump()] * 4
    result = preview_tactical(request(lots=lots, available_cash_usd=2005), NOW)
    assert result['cash_required_usd'] == 2012 and 'shared_cash_exceeded' in result['reasons']
    assert result['planned_loss_usd'] == 112


def test_fees_unknown_are_not_zero():
    req = request(); req.lots[0].round_trip_cost_usd = None
    result = preview_tactical(req, NOW)
    assert result['planned_loss_usd'] is None and result['remaining_cash_usd'] is None
    assert 'all_in_costs_required' in result['reasons']


def test_tolerance_not_default_stop_costs_also_count():
    req = request(); req.lots[0].planned_loss_pct = 40
    assert 'lot_risk_exceeded' in preview_tactical(req, NOW)['reasons']


@pytest.mark.parametrize('delta', [timedelta(days=-2), timedelta(seconds=1)])
def test_cash_timestamp_stale_or_future(delta):
    assert 'cash_timestamp_stale_or_future' in preview_tactical(request(cash_as_of=NOW + delta), NOW)['reasons']


def test_existing_budgets_must_be_excluded():
    assert 'cash_must_exclude_other_budgets' in preview_tactical(request(cash_net_of_other_budgets=False), NOW)['reasons']


@pytest.mark.parametrize('patch', [{'available_cash_usd': float('nan')}, {'cash_as_of': NOW.replace(tzinfo=None)},
    {'lots': []}, {'loss_tolerance_pct': 100}, {'available_cash_usd': -1}, {'place_order': True}])
def test_strict_inputs(patch):
    with pytest.raises(ValidationError):
        request(**patch)


def test_http_contract_is_stateless_and_never_executable(monkeypatch):
    from api.v1.endpoints.portfolio import router
    from src.storage import DatabaseManager
    def forbidden(*args, **kwargs):
        raise AssertionError('Preview must not open database')
    monkeypatch.setattr(DatabaseManager, 'get_instance', forbidden)
    app = FastAPI(); app.include_router(router, prefix='/portfolio')
    response = TestClient(app).post('/portfolio/tactical-research/preview', json=request().model_dump(mode='json'))
    assert response.status_code == 200 and response.json()['executable'] is False
