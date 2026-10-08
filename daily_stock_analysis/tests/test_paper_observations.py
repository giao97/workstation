"""Offline prospective observations; never open a real account or fetch quotes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.v1.endpoints import paper_observations as endpoint
from data_provider.paper_daily import PaperDataUnavailable, fetch_paper_daily
from src.config import Config
from src.core.paper_observation import PaperAssumptions, observe_window
from src.repositories.paper_repo import PaperRepository
from src.services.paper_observation_service import PaperObservationService, forward_sessions
from src.storage import DatabaseManager, DecisionSignalRecord, PaperExperimentRecord, PaperOutcomeRecord, PortfolioTrade

CAPTURE = datetime(2026, 9, 25, 22, tzinfo=timezone.utc)  # Friday, after close
ASSUMPTIONS = dict(quantity=20, baseline_shares=105, protected_shares=85, cash_usd=1000,
                   buy_fee_usd=1.04, sell_fee_usd=1.07, slippage_bps=10, fee_note="Synthetic test assumption")


def bar(day="2026-09-28", op=30, close=29, **overrides):
    return dict(date=day, open=op, high=max(op, close) + 1, low=min(op, close) - 1,
                close=close, volume=100000, previous_volume=100000, dividends=0, stock_splits=0, capital_gains=0, **overrides)


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    repo = PaperRepository()
    signal = dict(id=1, stock_code="EUV", market="us", action="reduce", status="active",
                  created_at="2026-09-25T20:00:00Z", updated_at="2026-09-25T20:00:00Z",
                  expires_at=None, reason="Synthetic test", metadata={})
    signals = Mock()
    signals.get_signal.side_effect = lambda _: deepcopy(signal)
    clock = Mock(return_value=CAPTURE)
    fetcher = Mock()
    service = PaperObservationService(repo, signals, fetcher, clock)
    yield service, signal, fetcher, clock
    DatabaseManager.reset_instance()
    Config.reset_instance()


def capture(service, assumptions=None, key="test_request_key_0001"):
    return service.capture(1, key, assumptions or ASSUMPTIONS)


def mature(setup, sessions=10, **bar_patch):
    service, _, fetcher, clock = setup
    calendar = forward_sessions(CAPTURE)
    now = calendar[sessions - 1]["close"] + timedelta(minutes=16)
    clock.return_value = now
    bars = [bar(calendar[0]["previous_date"])]
    for session in calendar[:sessions]:
        row = bar(session["date"])
        row.update(bar_patch)
        bars.append(row)
    fetcher.return_value = dict(symbol="EUV", currency="USD", source="test.raw",
                               url="https://example.com/history", fetched_at=now.isoformat(),
                               price_basis="auto_adjust_false_actions_checked", bars=bars)
    return fetcher.return_value


def test_decimal_round_trip_and_original_baseline():
    result = observe_window("reduce", ASSUMPTIONS, bar(), bar(), 3)
    # 20*(30*.999 - 29*1.001) - 2.11 = 16.71
    assert result["closed_net_pnl"] == 16.71
    assert result["relative_hold_pnl"] == 16.71
    assert result["economic_cost_improvement_per_share"] == pytest.approx(16.71 / 105, abs=1e-6)
    assert result["ending_shares"] == 105
    assert len(result["fills"]) == 2


def test_buy_then_sell_is_cash_benchmark_and_includes_losing_fees():
    args = dict(ASSUMPTIONS, quantity=10, baseline_shares=0, protected_shares=0, slippage_bps=0)
    result = observe_window("buy", args, bar(op=32.75, close=32.81), bar(op=32.75, close=32.81), 1)
    assert result["closed_net_pnl"] == -1.51
    assert result["opportunity_loss"] == 1.51
    assert result["baseline_kind"] == "unchanged_cash"
    assert result["economic_cost_improvement_per_share"] is None


@pytest.mark.parametrize("patch,action,reason", [
    ({"quantity": 21}, "sell", "protected_shares"),
    ({"cash_usd": 0}, "buy", "entry_cash_insufficient"),
    ({}, "watch", "non_directional_action"),
])
def test_no_fill_kept_instead_of_filtered(patch, action, reason):
    result = observe_window(action, dict(ASSUMPTIONS, **patch), bar(), bar(), 1)
    assert result["status"] == "no_fill"
    assert result["reason"] == reason
    assert result["fills"] == []


def test_sold_away_and_no_extra_capital():
    args = dict(ASSUMPTIONS, cash_usd=0)
    result = observe_window("sell", args, bar(), bar(op=40, close=40), 3)
    assert result["status"] == "open"
    assert result["relative_hold_pnl"] == -201.67
    assert result["ending_shares"] == 85
    assert result["economic_cost_improvement_per_share"] is None
    assert len(result["fills"]) == 1


def test_same_day_unsettled_sales_not_reused():
    args = dict(ASSUMPTIONS, cash_usd=0)
    assert observe_window("sell", args, bar(), bar(), 1)["status"] == "open"
    assert observe_window("sell", args, bar(), bar(), 3)["status"] == "completed"


def test_volume_cap_does_not_infer_fill_from_price_touch():
    first, last = bar(), bar()
    first["volume"] = 0
    assert observe_window("buy", ASSUMPTIONS, first, last, 3)["reason"] == "entry_liquidity_insufficient"
    first["volume"] = 100000
    last["volume"] = 100
    last["previous_volume"] = 100
    assert observe_window("sell", ASSUMPTIONS, first, last, 3)["status"] == "open"


def test_liquidity_filter_uses_previously_available_volume_not_future_total():
    first = bar()
    first.update(previous_volume=100, volume=10000000)
    assert observe_window("buy", ASSUMPTIONS, first, bar(), 1)["status"] == "no_fill"
    last = bar()
    last["volume"] = 0
    result = observe_window("buy", ASSUMPTIONS, bar(), last, 3)
    assert result["status"] == "open"
    assert result["relative_hold_pnl"] is None


@pytest.mark.parametrize("patch", [{"buy_fee_usd": float("nan")}, {"quantity": 1.5}, {"quantity": True},
                                   {"protected_shares": 106}, {"fee_note": " "}, {"slippage_bps": -1}])
def test_invalid_assumptions(patch):
    with pytest.raises(ValueError):
        PaperAssumptions.model_validate(dict(ASSUMPTIONS, **patch))


def test_archive_immutable_and_retries_idempotent(setup):
    service, signal, _, clock = setup
    item = capture(service)
    signal["action"] = "buy"
    clock.return_value += timedelta(days=2)
    assert capture(service) == item
    assert service.get(item["id"])["snapshot"]["action"] == "reduce"
    assert service.get(item["id"])["captured_at"] == CAPTURE.isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="conflict"):
        capture(service, dict(ASSUMPTIONS, quantity=1))
    with service.repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(PaperExperimentRecord)) == 1
        assert session.scalar(select(func.count()).select_from(PortfolioTrade)) == 0


def test_cannot_backdate_capture_to_source_signal(setup):
    service, signal, fetcher, _ = setup
    signal["created_at"] = "2025-01-01T00:00:00Z"
    signal["updated_at"] = "2025-01-01T00:00:00Z"
    item = capture(service)
    result = service.evaluate(item["id"])
    assert all(row["status"] == "pending" for row in result["items"])
    fetcher.assert_not_called()


@pytest.mark.parametrize("field,value", [("market", "cn"), ("updated_at", "2030-01-01T00:00:00Z")])
def test_capture_rejects_unsupported_or_future_sources(setup, field, value):
    service, signal, _, _ = setup
    signal[field] = value
    with pytest.raises(ValueError):
        capture(service)


def test_forward_sessions_holidays_dst_and_half_day():
    assert forward_sessions(CAPTURE)[0]["date"] == "2026-09-28"
    sessions = forward_sessions(datetime(2026, 11, 25, 22, tzinfo=timezone.utc))
    assert sessions[0]["date"] == "2026-11-27"  # Thanksgiving skipped
    assert sessions[0]["close"].hour == 18  # half-day 13:00 EST


def test_complete_windows_archive_evidence_and_never_recompute(setup):
    service, _, fetcher, _ = setup
    item = capture(service)
    evidence = mature(setup)
    result = service.evaluate(item["id"])
    assert [r["horizon"] for r in result["items"]] == [1, 3, 5, 10]
    assert all(r["status"] == "completed" for r in result["items"])
    fetcher.reset_mock()
    fetcher.side_effect = RuntimeError("must not refetch finalized observations")
    assert service.evaluate(item["id"])["items"] == result["items"]
    assert service.repo.evidence(item["id"], 3, "paper-window-v1") == evidence
    fetcher.assert_not_called()
    with service.repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(PaperOutcomeRecord)) == 4
        assert session.scalar(select(func.count()).select_from(PortfolioTrade)) == 0


def test_partial_windows_only_evaluate_complete_sessions(setup):
    service, _, _, clock = setup
    item = capture(service)
    evidence = mature(setup, sessions=3)
    clock.return_value -= timedelta(minutes=2)  # before 15m publication buffer
    evidence["fetched_at"] = clock.return_value.isoformat()
    rows = service.evaluate(item["id"])["items"]
    assert rows[0]["status"] == "completed"
    assert [r["status"] for r in rows[1:]] == ["pending"] * 3


@pytest.mark.parametrize("change,reason", [
    (lambda e: e.update(price_basis="qfq"), "daily_provenance_missing"),
    (lambda e: e.update(currency="CNY"), "daily_provenance_missing"),
    (lambda e: e["bars"][0].update(stock_splits=2), "corporate_action_unsupported"),
    (lambda e: e["bars"][-1].update(dividends=1), "corporate_action_unsupported"),
    (lambda e: e["bars"][0].update(close=float("nan")), "invalid_daily_bar"),
    (lambda e: e["bars"].append(e["bars"][0]), "invalid_daily_bar"),
    (lambda e: e["bars"][0].update(low=1000), "invalid_daily_bar"),
    (lambda e: e.update(fetched_at="2025-01-01T00:00:00Z"), "invalid_daily_bar"),
])
def test_untrusted_data_never_turns_into_profit(setup, change, reason):
    service, _, _, _ = setup
    item = capture(service)
    evidence = mature(setup)
    change(evidence)
    results = service.evaluate(item["id"])["items"]
    assert all(row["reason"] == reason and "relative_hold_pnl" not in row for row in results)
    assert service.repo.outcomes(item["id"], "paper-window-v1") == {}


def test_missing_session_not_skipped_and_retry_can_recover(setup):
    service, _, _, _ = setup
    item = capture(service)
    evidence = mature(setup)
    evidence["bars"].pop(2)
    rows = service.evaluate(item["id"])["items"]
    assert rows[0]["status"] == "completed"
    assert rows[1]["reason"] == "missing_session_bar"
    mature(setup)
    assert all(r["status"] == "completed" for r in service.evaluate(item["id"])["items"])


def test_expired_signal_preserves_no_fill(setup):
    service, signal, _, _ = setup
    signal["expires_at"] = "2026-09-28T13:30:00Z"
    item = capture(service)
    mature(setup)
    assert all(r["reason"] == "signal_inactive_before_entry" for r in service.evaluate(item["id"])["items"])


def test_calendar_or_provider_failure_is_blocked_not_zero(setup, monkeypatch):
    service, _, fetcher, _ = setup
    item = capture(service)
    mature(setup)
    fetcher.side_effect = PaperDataUnavailable("daily_provider_unavailable")
    assert service.evaluate(item["id"])["items"][0]["status"] == "blocked"
    monkeypatch.setattr("src.core.trading_calendar._XCALS_AVAILABLE", False)
    assert service.evaluate(item["id"])["items"][0]["reason"] == "calendar_unavailable"


def test_api_create_list_evaluate_evidence_and_validation(setup, monkeypatch):
    service, _, _, _ = setup
    monkeypatch.setattr(endpoint, "PaperObservationService", lambda: service)
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/paper-observations")
    client = TestClient(app)
    payload = dict(signal_id=1, request_key="api_request_key_01", assumptions=ASSUMPTIONS)
    response = client.post("/paper-observations", json=payload)
    assert response.status_code == 200
    item = response.json()
    assert client.post("/paper-observations", json=payload).json()["id"] == item["id"]
    assert len(client.get("/paper-observations?signal_id=1").json()["items"]) == 1
    assert client.get("/paper-observations?signal_id=2").json()["items"] == []
    assert client.post("/paper-observations", json=dict(payload, captured_at="2020-01-01")).status_code == 422
    assert client.post("/paper-observations/999/evaluate").status_code == 404
    assert client.get(f'/paper-observations/{item["id"]}/evidence/1').status_code == 404
    mature(setup)
    assert client.post(f'/paper-observations/{item["id"]}/evaluate').json()["items"][0]["status"] == "completed"
    assert client.get(f'/paper-observations/{item["id"]}/evidence/1').json()["currency"] == "USD"


def test_raw_provider_contract_and_no_adjusted_fallback(monkeypatch):
    import yfinance
    ticker = Mock()
    ticker.history_metadata = dict(symbol="EUV", currency="USD", exchangeTimezoneName="America/New_York", instrumentType="ETF")
    ticker.history.return_value = pd.DataFrame({"Open": [30], "High": [31], "Low": [28], "Close": [29],
                                               "Volume": [100000], "Dividends": [0], "Stock Splits": [0], "Capital Gains": [0]},
                                              index=pd.DatetimeIndex(["2026-09-28"], tz="America/New_York"))
    monkeypatch.setattr(yfinance, "Ticker", lambda _: ticker)
    data = fetch_paper_daily("EUV", CAPTURE.date(), CAPTURE.date() + timedelta(days=3))
    assert data["bars"][0]["close"] == 29
    assert ticker.history.call_args.kwargs["auto_adjust"] is False
    assert ticker.history.call_args.kwargs["actions"] is True
    ticker.history_metadata["currency"] = "CAD"
    with pytest.raises(PaperDataUnavailable, match="currency"):
        fetch_paper_daily("EUV", CAPTURE.date(), CAPTURE.date())
    ticker.history.side_effect = RuntimeError("provider secret must not appear")
    with pytest.raises(PaperDataUnavailable, match="daily_provider_unavailable"):
        fetch_paper_daily("EUV", CAPTURE.date(), CAPTURE.date())


def test_real_signal_serializer_and_clock_not_historical_report_date(setup):
    service, _, fetcher, clock = setup
    with service.repo.db.get_session() as session:
        session.add(DecisionSignalRecord(id=1, stock_code="EUV", market="us", source_type="manual",
                                        trigger_source="test", action="reduce", horizon="10d", status="active",
                                        created_at=CAPTURE.replace(tzinfo=None), updated_at=CAPTURE.replace(tzinfo=None),
                                        reason="Original persisted source", metadata_json='{"test": true}'))
        session.commit()
    real = PaperObservationService(repo=service.repo, fetcher=fetcher, clock=clock)
    item = capture(real)
    assert item["snapshot"]["reason"] == "Original persisted source"
    assert item["snapshot"]["metadata"] == {"test": True}
    assert item["snapshot"]["paper_policy_version"] == "paper-window-v1"


def test_global_auth_middleware_covers_new_routes(setup, monkeypatch):
    from api.middlewares.auth import add_auth_middleware
    monkeypatch.setattr("api.middlewares.auth.is_auth_enabled", lambda: True)
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1/paper-observations")
    add_auth_middleware(app)
    client = TestClient(app)
    assert client.get("/api/v1/paper-observations").status_code == 401
    assert client.post("/api/v1/paper-observations/1/evaluate").status_code == 401
