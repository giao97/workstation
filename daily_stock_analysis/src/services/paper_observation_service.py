"""Prospective, immutable, manual-run paper observations, isolated from trades."""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

from data_provider.paper_daily import PaperDataUnavailable, fetch_paper_daily, fetch_paper_minutes
from src.core import trading_calendar
from src.core.paper_observation import ENGINE_VERSION, HORIZONS, PaperAssumptions, observe_window
from src.core.paper_minute import MINUTE_ENGINE_VERSION, MinuteRules, replay_minutes
from src.repositories.paper_repo import PaperRepository, digest
from src.services.decision_signal_service import DecisionSignalService
from src.storage import to_utc_naive_datetime


def _timestamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def forward_sessions(captured_at):
    """Strictly AFTER the capture's exchange-local day; fail closed on calendar."""
    if not trading_calendar._XCALS_AVAILABLE:
        raise PaperDataUnavailable("calendar_unavailable")
    try:
        local_day = captured_at.astimezone(ZoneInfo("America/New_York")).date()
        cal = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE["us"])
        sessions = cal.sessions_in_range(local_day + timedelta(days=1), local_day + timedelta(days=35))[:10]
        if len(sessions) != 10:
            raise ValueError("Incomplete calendar")
        return [dict(date=day.date().isoformat(), previous_date=cal.previous_session(day).date().isoformat(),
                     open=cal.session_open(day).to_pydatetime(),
                     close=cal.session_close(day).to_pydatetime()) for day in sessions]
    except Exception as exc:
        raise PaperDataUnavailable("calendar_unavailable") from exc


def freeze_minute_session(now, rules, snapshot):
    """Freeze the calendar window at capture, never reconstruct from old reports."""
    expiry = _timestamp(rules["expires_at"])
    if not now < expiry <= now + timedelta(days=7):
        raise ValueError("minute_expiry_out_of_range")
    if snapshot["status"] != "active" or snapshot["action"] not in {"buy", "add", "reduce", "sell"}:
        raise ValueError("minute_requires_active_directional_signal")
    if snapshot.get("expires_at") and expiry > _timestamp(snapshot["expires_at"]):
        raise ValueError("minute_exceeds_signal_expiry")
    entry, target, invalid = (rules[k] for k in ("entry_price", "exit_price", "invalidation_price"))
    if not (invalid < entry < target if snapshot["action"] in {"buy", "add"} else target < entry < invalid):
        raise ValueError("minute_price_order_invalid")
    if not trading_calendar._XCALS_AVAILABLE:
        raise ValueError("calendar_unavailable")
    try:
        cal = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE["us"])
        day = expiry.astimezone(ZoneInfo("America/New_York")).date()
        session = cal.date_to_session(day, direction="none")
        opening, closing = (fn(session).to_pydatetime() for fn in (cal.session_open, cal.session_close))
    except Exception as exc:
        raise ValueError("calendar_unavailable") from exc
    start = max(opening + timedelta(minutes=1), now.replace(second=0, microsecond=0) + timedelta(minutes=1))
    if expiry > closing or expiry < start + timedelta(minutes=2):
        raise ValueError("minute_expiry_outside_session")
    return dict(date=day.isoformat(), start=start.isoformat(), end=expiry.isoformat(),
                warmup=(start - timedelta(minutes=1)).isoformat(), session_close=closing.isoformat())


class PaperObservationService:
    def __init__(self, repo=None, signals=None, fetcher=None, clock=None, minute_fetcher=None):
        self.repo = repo or PaperRepository()
        self.signals = signals or DecisionSignalService(db_manager=self.repo.db)
        self.fetcher = fetcher or fetch_paper_daily
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.minute_fetcher = minute_fetcher or fetch_paper_minutes

    def capture(self, signal_id, request_key, assumptions, minute_rules=None):
        assumptions = PaperAssumptions.model_validate(assumptions).model_dump()
        rules = MinuteRules.model_validate(minute_rules).model_dump(mode="json") if minute_rules is not None else None
        existing = self.repo.by_key(request_key)
        if existing:
            return self._same_request(existing, signal_id, assumptions, rules)
        snapshot = self.signals.get_signal(signal_id)
        # The policy is frozen too: future engines must not reinterpret archives.
        snapshot["paper_policy_version"] = MINUTE_ENGINE_VERSION if rules else ENGINE_VERSION
        now = self.clock().astimezone(timezone.utc)
        if snapshot["market"] != "us":
            raise ValueError("paper_us_only")
        for key in ("created_at", "updated_at"):
            if snapshot.get(key) and _timestamp(snapshot[key]) > now:
                raise ValueError("signal_timestamp_in_future")
        if rules:
            snapshot["minute_rules"] = rules
            snapshot["minute_session"] = freeze_minute_session(now, rules, snapshot)
        item = self.repo.create(request_key, signal_id, snapshot, assumptions, to_utc_naive_datetime(now))
        return self._same_request(item, signal_id, assumptions, rules)

    @staticmethod
    def _same_request(item, signal_id, assumptions, minute_rules=None):
        if (item["signal_id"] != signal_id or item["assumptions"] != assumptions
                or item["snapshot"].get("minute_rules") != minute_rules):
            raise ValueError("paper_request_key_conflict")
        return item

    def get(self, experiment_id):
        item = self.repo.get(experiment_id)
        if not item:
            raise LookupError("paper_experiment_not_found")
        return item

    def evaluate(self, experiment_id):
        experiment = self.get(experiment_id)
        if experiment["snapshot"].get("paper_policy_version") == MINUTE_ENGINE_VERSION:
            return self._evaluate_minute(experiment)
        saved = self.repo.outcomes(experiment_id, ENGINE_VERSION)
        now = self.clock().astimezone(timezone.utc)
        response = dict(experiment=experiment, engine_version=ENGINE_VERSION, observed_at=now.isoformat(),
                        policy="next_session_open_to_horizon_close", currency="USD", items=[])
        pending = [h for h in HORIZONS if h not in saved]
        if not pending:
            response["items"] = [saved[h] for h in HORIZONS]
            return response
        captured = _timestamp(experiment["captured_at"])
        try:
            if experiment["snapshot"].get("paper_policy_version") != ENGINE_VERSION:
                raise PaperDataUnavailable("policy_version_unsupported")
            if now < captured:
                raise PaperDataUnavailable("clock_precedes_capture")
            if now - captured > timedelta(days=365):
                raise PaperDataUnavailable("observation_window_too_old")
            sessions = forward_sessions(captured)
            mature = [h for h in pending if sessions[h - 1]["close"] + timedelta(minutes=15) <= now]
            evidence = None
            if mature:
                evidence = self.fetcher(experiment["snapshot"]["stock_code"],
                                        datetime.fromisoformat(sessions[0]["previous_date"]).date(),
                                        now.astimezone(ZoneInfo("America/New_York")).date())
                self._validate_evidence(evidence, experiment["snapshot"]["stock_code"], now)
            bars = {bar["date"]: bar for bar in evidence["bars"]} if evidence else {}
            for horizon in pending:
                result = dict(horizon=horizon, status="pending", reason="awaiting_completed_sessions")
                if horizon in mature:
                    expected = [s["date"] for s in sessions[:horizon]]
                    volume_dates = [sessions[0]["previous_date"], sessions[horizon - 1]["previous_date"]]
                    if not all(day in bars for day in expected + volume_dates):
                        result = dict(horizon=horizon, status="blocked", reason="missing_session_bar")
                    else:
                        snapshot = experiment["snapshot"]
                        expiry = _timestamp(snapshot["expires_at"]) if snapshot.get("expires_at") else None
                        if snapshot["status"] != "active" or (expiry and expiry <= sessions[0]["open"]):
                            result = dict(horizon=horizon, status="no_fill", reason="signal_inactive_before_entry",
                                          relative_hold_pnl=0.0, fills=[])
                        else:
                            result = observe_window(snapshot["action"], experiment["assumptions"],
                                                    dict(bars[expected[0]], previous_volume=bars[volume_dates[0]]["volume"]),
                                                    dict(bars[expected[-1]], previous_volume=bars[volume_dates[1]]["volume"]), horizon)
                        result.update(observed_at=now.isoformat(), evidence_hash=digest(evidence),
                                      source=evidence["source"], source_url=evidence["url"],
                                      fetched_at=evidence["fetched_at"], price_basis=evidence["price_basis"])
                        result = self.repo.save_outcome(experiment_id, horizon, ENGINE_VERSION, result,
                                                       evidence, to_utc_naive_datetime(now))
                saved[horizon] = result
        except PaperDataUnavailable as exc:
            for horizon in pending:
                saved[horizon] = dict(horizon=horizon, status="blocked", reason=str(exc))
        response["items"] = [saved[h] for h in HORIZONS]
        return response

    def _evaluate_minute(self, experiment):
        now = self.clock().astimezone(timezone.utc)
        snapshot = experiment["snapshot"]
        window = snapshot["minute_session"]
        expiry, start, warmup = (_timestamp(window[k]) for k in ("end", "start", "warmup"))
        saved = self.repo.outcomes(experiment["id"], MINUTE_ENGINE_VERSION)
        response = dict(experiment=experiment, engine_version=MINUTE_ENGINE_VERSION, currency="USD",
                        observed_at=now.isoformat(), policy="close_confirm_next_minute_bounded_open", items=[])
        result = dict(horizon=0, status="pending", reason="minute_awaiting_expiry")
        try:
            if 0 in saved:
                result = saved[0]
            elif now < _timestamp(experiment["captured_at"]):
                raise PaperDataUnavailable("clock_precedes_capture")
            elif now < expiry + timedelta(minutes=15):
                pass  # Historical replay, not an intraday execution signal.
            elif now - warmup > timedelta(days=6):
                raise PaperDataUnavailable("minute_history_window_expired")
            else:
                # Daily corporate-action coverage through retrieval protects old
                # minute bars from later split/distribution price-basis changes.
                day = datetime.fromisoformat(window["date"]).date()
                through = now.astimezone(ZoneInfo("America/New_York")).date()
                daily = self.fetcher(snapshot["stock_code"], day, through)
                minute = self.minute_fetcher(snapshot["stock_code"], warmup, expiry)
                observed = self.clock().astimezone(timezone.utc)
                if daily.get("interval") != "1d":
                    raise PaperDataUnavailable("daily_provenance_missing")
                self._validate_evidence(daily, snapshot["stock_code"], observed)
                if not trading_calendar._XCALS_AVAILABLE:
                    raise PaperDataUnavailable("calendar_unavailable")
                try:
                    cal = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE["us"])
                    required_days = {d.date().isoformat() for d in cal.sessions_in_range(day, through)}
                except Exception as exc:
                    raise PaperDataUnavailable("calendar_unavailable") from exc
                if not required_days.issubset({b["date"] for b in daily["bars"]}):
                    raise PaperDataUnavailable("missing_session_bar")
                self._validate_minutes(minute, snapshot["stock_code"], warmup, expiry, observed)
                result = replay_minutes(snapshot["action"], experiment["assumptions"], snapshot["minute_rules"], minute["bars"])
                evidence = dict(minute=minute, corporate_action_daily=daily, window=window)
                result.update(observed_at=observed.isoformat(), evidence_hash=digest(evidence),
                              source=minute["source"], source_url=minute["url"], fetched_at=minute["fetched_at"],
                              price_basis=minute["price_basis"], observation_start=start.isoformat())
                result = self.repo.save_outcome(experiment["id"], 0, MINUTE_ENGINE_VERSION, result,
                                               evidence, to_utc_naive_datetime(observed))
        except PaperDataUnavailable as exc:
            result = dict(horizon=0, status="blocked", reason=str(exc))
        response["items"] = [result]
        return response

    @staticmethod
    def _validate_minutes(evidence, symbol, start, end, now):
        if (evidence.get("symbol") != symbol or evidence.get("currency") != "USD"
                or evidence.get("interval") != "1m"
                or evidence.get("price_basis") != "auto_adjust_false_actions_checked"
                or not evidence.get("source") or not evidence.get("url")):
            raise PaperDataUnavailable("minute_provenance_missing")
        try:
            # Unlike legacy daily fields, minute evidence requires aware timestamps.
            fetched = datetime.fromisoformat(evidence["fetched_at"].replace("Z", "+00:00"))
            if fetched.tzinfo is None or fetched > now + timedelta(minutes=1) or now - fetched > timedelta(minutes=5):
                raise ValueError("unverifiable fetch time")
            expected = start
            for bar in evidence["bars"]:
                stamp = datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp != expected or stamp >= end or stamp + timedelta(minutes=1) > now:
                    raise PaperDataUnavailable("minute_gap_or_time_invalid")
                expected += timedelta(minutes=1)
                numbers = [bar[k] for k in ("open", "high", "low", "close", "volume", "dividends", "stock_splits", "capital_gains")]
                if not all(math.isfinite(float(value)) for value in numbers):
                    raise ValueError("nonfinite minute")
                if not (0 < bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]
                        and bar["volume"] >= 0):
                    raise ValueError("invalid OHLC")
                if any(bar[k] != 0 for k in ("dividends", "stock_splits", "capital_gains")):
                    raise PaperDataUnavailable("corporate_action_unsupported")
            if expected != end:
                raise PaperDataUnavailable("minute_gap_or_time_invalid")
        except PaperDataUnavailable:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise PaperDataUnavailable("invalid_minute_bar") from exc

    @staticmethod
    def _validate_evidence(evidence, symbol, now):
        if (evidence.get("symbol") != symbol or evidence.get("currency") != "USD"
                or evidence.get("price_basis") != "auto_adjust_false_actions_checked"
                or not evidence.get("source") or not evidence.get("url")):
            raise PaperDataUnavailable("daily_provenance_missing")
        try:
            fetched = _timestamp(evidence["fetched_at"])
            if fetched > now + timedelta(minutes=1) or now - fetched > timedelta(minutes=5):
                raise ValueError("stale evidence")
            days = set()
            for bar in evidence["bars"]:
                day = datetime.fromisoformat(bar["date"]).date()
                if day in days or day > now.astimezone(ZoneInfo("America/New_York")).date():
                    raise ValueError("duplicate/future date")
                days.add(day)
                numbers = [bar[k] for k in ("open", "high", "low", "close", "volume", "dividends", "stock_splits", "capital_gains")]
                if not all(math.isfinite(float(n)) for n in numbers):
                    raise ValueError("nonfinite value")
                if not (0 < bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]
                        and bar["volume"] >= 0):
                    raise ValueError("inconsistent OHLC")
                if any(bar[k] != 0 for k in ("dividends", "stock_splits", "capital_gains")):
                    raise PaperDataUnavailable("corporate_action_unsupported")
        except PaperDataUnavailable:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise PaperDataUnavailable("invalid_daily_bar") from exc
