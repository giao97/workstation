"""Minute policy regression tests with immutable temporary paper archives."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.v1.endpoints import paper_observations as endpoint
from data_provider.paper_daily import PaperDataUnavailable, fetch_paper_minutes
from src.core.paper_minute import MINUTE_ENGINE_VERSION, MinuteRules, replay_minutes
from src.services.paper_observation_service import freeze_minute_session
from src.storage import PortfolioTrade
from tests.test_paper_observations import ASSUMPTIONS, bar, setup  # noqa: F401

NOW = datetime(2026, 9, 28, 13, 30, 20, tzinfo=timezone.utc)
RULES = dict(entry_price=30, exit_price=29, invalidation_price=33, expires_at="2026-09-28T13:36:00Z")


def candles():
    pairs = [(30.5, 30.5), (29.8, 30.3), (30.5, 30.2), (29.2, 28.8), (28.7, 28.9), (28.9, 29)]
    return [dict(timestamp=f"2026-09-28T13:{30+i:02d}:00+00:00", open=op, close=close,
                 high=max(op, close) + .1, low=min(op, close) - .1, volume=100000,
                 dividends=0, stock_splits=0, capital_gains=0) for i, (op, close) in enumerate(pairs)]


@pytest.fixture()
def minute_setup(setup):
    service, signal, fetcher, clock = setup
    clock.return_value = NOW
    service.minute_fetcher = Mock()
    return service, signal, fetcher, clock


def capture(env, rules=None, assumptions=None, key="minute_request_001"):
    return env[0].capture(1, key, assumptions or ASSUMPTIONS, rules or RULES)


def ready(env):
    service, _, fetcher, clock = env
    clock.return_value = datetime(2026, 9, 28, 13, 51, tzinfo=timezone.utc)
    base = dict(symbol="EUV", currency="USD", source="test.raw", url="https://example.com/history",
                fetched_at=clock.return_value.isoformat(), price_basis="auto_adjust_false_actions_checked")
    fetcher.return_value = dict(base, interval="1d", bars=[bar("2026-09-28")])
    service.minute_fetcher.return_value = dict(base, interval="1m", bars=candles())
    return service.minute_fetcher.return_value


def test_close_confirm_then_next_open_costs_and_same_quantity():
    result = replay_minutes("reduce", ASSUMPTIONS, RULES, candles())
    assert result["status"] == "completed"
    assert [f["timestamp"] for f in result["fills"]] == [candles()[2]["timestamp"], candles()[4]["timestamp"]]
    assert result["closed_net_pnl"] == 32.706
    assert result["economic_cost_improvement_per_share"] == pytest.approx(32.706 / 105, abs=1e-6)
    assert result["ending_shares"] == 105


def test_buy_then_sell_zero_baseline_does_not_claim_cost_reduction():
    rows = candles()
    for row in rows:
        row.update(open=30, close=30, low=29.9, high=30.1)
    rows[1].update(close=29.5, low=29.4)
    rows[2].update(open=29.5, low=29.4)
    rows[3].update(close=31.5, high=31.6)
    rows[4].update(open=31.5, high=31.6)
    result = replay_minutes("buy", dict(ASSUMPTIONS, baseline_shares=0, protected_shares=0),
                            dict(RULES, entry_price=30, exit_price=31, invalidation_price=28), rows)
    assert result["status"] == "completed"
    assert result["baseline_kind"] == "unchanged_cash"
    assert result["economic_cost_improvement_per_share"] is None


def test_fees_can_turn_small_gross_gain_into_loss():
    result = replay_minutes("sell", dict(ASSUMPTIONS, buy_fee_usd=20, sell_fee_usd=20), RULES, candles())
    assert result["closed_net_pnl"] < 0
    assert result["opportunity_loss"] == -result["relative_hold_pnl"]


def test_warmup_and_wicks_cannot_trigger_entries():
    rows = candles()
    rows[0].update(open=35, close=35, high=35, low=35)
    for row in rows[1:]:
        row.update(open=29.8, close=29.8, high=30.5, low=29.7)
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["status"] == "no_fill"
    assert result["fills"] == []


def test_same_bar_target_and_invalidation_keeps_losing_entry_not_success():
    rows = candles()
    rows[2].update(high=34, low=28)
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["status"] == "open"
    assert len(result["fills"]) == 1  # entry occurred at open BEFORE the high/low
    assert result["reason"] == "minute_ambiguous_range"
    assert result["economic_cost_improvement_per_share"] is None


def test_opening_gap_invalidates_without_optimistic_fill():
    rows = candles()
    rows[2].update(open=34, high=34.1)
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["fills"] == []
    assert result["reason"] == "minute_invalidated"


def test_reversal_at_open_is_before_later_candle_invalidation():
    rows = candles()
    rows[4]["high"] = 35
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["status"] == "completed"


def test_slippage_bound_and_prior_volume_checked():
    rows = candles()
    rows[2]["open"] = 30  # adverse sell price now below entry floor
    rows[2]["volume"] = 10_000_000
    rows[1]["volume"] = 1
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["events"][0]["reason"] == "minute_price_bound"
    rows[2]["open"] = 30.5
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["events"][0]["reason"] == "minute_liquidity_insufficient"
    assert not result["fills"]


def test_same_day_cash_no_sale_proceeds_and_no_forced_buyback():
    result = replay_minutes("sell", dict(ASSUMPTIONS, cash_usd=0), RULES, candles())
    assert result["status"] == "open"
    assert result["reason"] == "exit_cash_insufficient"
    assert result["ending_shares"] == 85
    assert result["closed_net_pnl"] is None


def test_core_protection_and_no_zero_volume_mark():
    result = replay_minutes("sell", dict(ASSUMPTIONS, protected_shares=105), RULES, candles())
    assert result["reason"] == "protected_shares"
    rows = candles()
    rows[-1]["volume"] = 0
    result = replay_minutes("sell", dict(ASSUMPTIONS, cash_usd=0), RULES, rows)
    assert result["relative_hold_pnl"] is None


def test_no_fill_when_only_last_minute_confirms():
    rows = candles()
    for row in rows[1:-1]:
        row.update(open=29.5, close=29.5, high=29.6, low=29.4)
    rows[-1].update(close=30.5, high=30.6)
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert result["reason"] == "minute_no_next_bar"
    assert result["fills"] == []


def test_rejected_entry_is_not_final_reason_after_a_later_fill():
    rows = candles()
    rows[2]["open"] = 30  # first attempt fails after adverse slippage
    rows[3].update(open=30.5, close=30.2, high=30.6, low=30.1)
    rows[4].update(open=30.2, close=30.2, high=30.3, low=30.1)
    rows[5].update(open=30.2, close=30.2, high=30.3, low=30.1)
    result = replay_minutes("sell", ASSUMPTIONS, RULES, rows)
    assert len(result["fills"]) == 1
    assert result["events"][0]["reason"] == "minute_price_bound"
    assert result["reason"] == "minute_exit_not_filled"


def test_freeze_after_capture_timezone_idempotency_and_no_retroactive_dates(minute_setup):
    item = capture(minute_setup)
    window = item["snapshot"]["minute_session"]
    assert window["start"] == "2026-09-28T13:31:00+00:00"
    assert window["warmup"] == "2026-09-28T13:30:00+00:00"
    minute_setup[3].return_value += timedelta(days=1)
    assert capture(minute_setup) == item  # uncertain retry doesn't reset clock
    with pytest.raises(ValueError, match="conflict"):
        capture(minute_setup, dict(RULES, exit_price=28))
    with pytest.raises(ValueError, match="conflict"):
        minute_setup[0].capture(1, "minute_request_001", ASSUMPTIONS)  # same key cannot switch to daily


@pytest.mark.parametrize("patch", [dict(expires_at="2026-09-28T13:36:00"), dict(expires_at="2026-09-28T13:36:10Z"),
                                   dict(entry_price=float("nan")), dict(exit_price=0)])
def test_rule_schema_rejects_ambiguous_or_invalid_values(patch):
    with pytest.raises(ValueError):
        MinuteRules.model_validate(dict(RULES, **patch))


@pytest.mark.parametrize("patch,reason", [(dict(exit_price=31), "price_order"),
                                         (dict(expires_at="2026-09-28T13:30:00Z"), "out_of_range"),
                                         (dict(expires_at="2026-09-28T20:01:00Z"), "outside_session"),
                                         (dict(expires_at="2026-09-28T13:32:00Z"), "outside_session")])
def test_invalid_capture_boundaries(minute_setup, patch, reason):
    with pytest.raises(ValueError, match=reason):
        capture(minute_setup, dict(RULES, **patch))


def test_expiry_cannot_extend_source_and_source_must_be_active(minute_setup):
    minute_setup[1]["expires_at"] = "2026-09-28T13:35:00Z"
    with pytest.raises(ValueError, match="signal_expiry"):
        capture(minute_setup)
    minute_setup[1]["status"] = "expired"
    with pytest.raises(ValueError, match="active_directional"):
        capture(minute_setup)


def test_holiday_half_day_and_standard_time_boundaries():
    snapshot = dict(status="active", action="sell")
    now = datetime(2026, 11, 25, 22, tzinfo=timezone.utc)
    rules = dict(RULES, expires_at="2026-11-27T18:00:00Z")
    window = freeze_minute_session(now, rules, snapshot)
    assert window["start"] == "2026-11-27T14:31:00+00:00"
    with pytest.raises(ValueError, match="outside_session"):
        freeze_minute_session(now, dict(rules, expires_at="2026-11-27T18:01:00Z"), snapshot)
    with pytest.raises(ValueError, match="calendar_unavailable"):
        freeze_minute_session(now, dict(rules, expires_at="2026-11-26T18:00:00Z"), snapshot)


def test_pending_never_fetches_and_terminal_never_rewrites(minute_setup):
    service, _, fetcher, _ = minute_setup
    item = capture(minute_setup)
    assert service.evaluate(item["id"])["items"][0]["status"] == "pending"
    service.minute_fetcher.assert_not_called()
    fetcher.assert_not_called()
    ready(minute_setup)
    result = service.evaluate(item["id"])
    assert result["items"][0]["status"] == "completed"
    service.minute_fetcher.side_effect = RuntimeError("no refetch")
    assert service.evaluate(item["id"])["items"] == result["items"]
    assert service.repo.evidence(item["id"], 0, MINUTE_ENGINE_VERSION)["minute"]["bars"] == candles()
    with service.repo.db.get_session() as session:
        assert session.scalar(select(func.count()).select_from(PortfolioTrade)) == 0


@pytest.mark.parametrize("alter,reason", [
    (lambda e: e["bars"].pop(2), "minute_gap_or_time_invalid"),
    (lambda e: e["bars"].append(e["bars"][-1]), "minute_gap_or_time_invalid"),
    (lambda e: e["bars"].reverse(), "minute_gap_or_time_invalid"),
    (lambda e: e["bars"][2].update(timestamp="2026-09-28T13:32:00"), "minute_gap_or_time_invalid"),
    (lambda e: e["bars"][0].update(timestamp="2026-09-28T13:29:00Z"), "minute_gap_or_time_invalid"),
    (lambda e: e.update(interval="5m"), "minute_provenance_missing"),
    (lambda e: e.update(currency="CNY"), "minute_provenance_missing"),
    (lambda e: e.update(fetched_at="2026-09-28T13:30:00Z"), "invalid_minute_bar"),
    (lambda e: e["bars"][2].update(close=float("nan")), "invalid_minute_bar"),
    (lambda e: e["bars"][2].update(dividends=1), "corporate_action_unsupported"),
])
def test_bad_minute_data_blocks_all_profit_without_persisting(minute_setup, alter, reason):
    service = minute_setup[0]
    item = capture(minute_setup)
    evidence = ready(minute_setup)
    alter(evidence)
    row = service.evaluate(item["id"])["items"][0]
    assert row == dict(horizon=0, status="blocked", reason=reason)
    assert service.repo.outcomes(item["id"], MINUTE_ENGINE_VERSION) == {}
    ready(minute_setup)
    assert service.evaluate(item["id"])["items"][0]["status"] == "completed"


def test_missing_daily_actions_and_retention_block(minute_setup):
    service, _, fetcher, clock = minute_setup
    item = capture(minute_setup)
    ready(minute_setup)
    fetcher.return_value["bars"][0]["stock_splits"] = 2
    assert service.evaluate(item["id"])["items"][0]["reason"] == "corporate_action_unsupported"
    ready(minute_setup)
    fetcher.return_value["interval"] = "1m"
    assert service.evaluate(item["id"])["items"][0]["reason"] == "daily_provenance_missing"
    ready(minute_setup)
    fetcher.return_value["bars"] = []
    assert service.evaluate(item["id"])["items"][0]["reason"] == "missing_session_bar"
    clock.return_value += timedelta(days=7)
    assert service.evaluate(item["id"])["items"][0]["reason"] == "minute_history_window_expired"


def test_api_minute_schema_and_evidence_dispatch(minute_setup, monkeypatch):
    service = minute_setup[0]
    monkeypatch.setattr(endpoint, "PaperObservationService", lambda: service)
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/paper-observations")
    client = TestClient(app)
    payload = dict(signal_id=1, request_key="minute_api_key_0001", assumptions=ASSUMPTIONS, minute_rules=RULES)
    created = client.post("/paper-observations", json=payload)
    assert created.status_code == 200
    item = created.json()
    assert item["snapshot"]["paper_policy_version"] == MINUTE_ENGINE_VERSION
    assert client.post("/paper-observations", json=dict(payload, minute_rules=dict(RULES, start="past"))).status_code == 422
    ready(minute_setup)
    response = client.post(f'/paper-observations/{item["id"]}/evaluate')
    assert response.json()["items"][0]["horizon"] == 0
    assert client.get(f'/paper-observations/{item["id"]}/evidence/0').json()["minute"]["interval"] == "1m"
    assert client.get(f'/paper-observations/{item["id"]}/evidence/1').status_code == 404


def test_provider_exact_one_minute_no_resampling_or_adjustment(monkeypatch):
    import yfinance
    ticker = Mock()
    ticker.history_metadata = dict(symbol="EUV", currency="USD", exchangeTimezoneName="America/New_York", instrumentType="ETF")
    ticker.history.return_value = pd.DataFrame({"Open": [30], "High": [31], "Low": [29], "Close": [30], "Volume": [1000],
                                               "Dividends": [0], "Stock Splits": [0], "Capital Gains": [0]},
                                              index=pd.DatetimeIndex(["2026-09-28T09:30:00"], tz="America/New_York"))
    monkeypatch.setattr(yfinance, "Ticker", lambda _: ticker)
    evidence = fetch_paper_minutes("EUV", NOW, NOW + timedelta(minutes=5))
    assert evidence["bars"][0]["timestamp"] == "2026-09-28T13:30:00+00:00"
    assert ticker.history.call_args.kwargs["interval"] == "1m"
    assert ticker.history.call_args.kwargs["auto_adjust"] is False
    with pytest.raises(PaperDataUnavailable):
        fetch_paper_minutes("EUV", NOW.replace(tzinfo=None), NOW)
    ticker.history.side_effect = RuntimeError("private exception")
    with pytest.raises(PaperDataUnavailable, match="minute_provider_unavailable"):
        fetch_paper_minutes("EUV", NOW, NOW + timedelta(minutes=5))
