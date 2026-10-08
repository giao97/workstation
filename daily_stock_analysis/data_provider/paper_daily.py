"""Dedicated raw daily observations; never reuse the adjusted StockDaily cache."""
from datetime import datetime, timedelta, timezone
import math
import re


class PaperDataUnavailable(ValueError):
    pass


def fetch_paper_daily(symbol: str, start, end) -> dict:
    """USD US listings only, one bounded request, no adjusted-data fallback.

    auto_adjust=False alone is NOT a no-split guarantee. The evaluator rejects
    every window with splits/distributions, and archives the original evidence.
    """
    return _fetch_history(symbol, start.isoformat(), (end + timedelta(days=1)).isoformat(), "1d")


def fetch_paper_minutes(symbol: str, start: datetime, end: datetime) -> dict:
    """Bounded one-session UTC request; no resampling or daily fallback."""
    if start.tzinfo is None or end.tzinfo is None or not timedelta(0) < end - start <= timedelta(hours=7):
        raise PaperDataUnavailable("minute_request_invalid")
    return _fetch_history(symbol, start, end, "1m")


def _fetch_history(symbol, start, end, interval):
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
        raise PaperDataUnavailable("unsupported_symbol")
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(start=start, end=end,
                               interval=interval, auto_adjust=False, back_adjust=False, repair=False,
                               actions=True, keepna=True, prepost=False, timeout=15, raise_errors=True)
        metadata = ticker.history_metadata
        if (metadata.get("currency") != "USD" or metadata.get("exchangeTimezoneName") != "America/New_York"
                or metadata.get("instrumentType") not in {"EQUITY", "ETF"}
                or str(metadata.get("symbol", "")).upper() != symbol):
            raise PaperDataUnavailable("currency_or_market_unverified")
        required = {"Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"}
        if metadata["instrumentType"] == "ETF":
            required.add("Capital Gains")
        if frame.empty or not required.issubset(frame.columns) or frame.index.tz is None:
            raise PaperDataUnavailable("daily_provenance_missing")
        bars = []
        for timestamp, row in frame.iterrows():
            bar = {key.lower().replace(" ", "_"): float(row[key]) for key in required}
            bar["capital_gains"] = float(row.get("Capital Gains", 0))
            if not all(math.isfinite(value) for value in bar.values()):
                raise PaperDataUnavailable("invalid_daily_bar")
            bar["date"] = timestamp.tz_convert("America/New_York").date().isoformat()
            if interval == "1m":
                bar["timestamp"] = timestamp.tz_convert("UTC").isoformat()
            bars.append(bar)
        return dict(symbol=symbol, currency="USD", source="yfinance.history",
                    url=f"https://finance.yahoo.com/quote/{symbol}/history/",
                    fetched_at=datetime.now(timezone.utc).isoformat(), price_basis="auto_adjust_false_actions_checked", interval=interval,
                    bars=bars)
    except PaperDataUnavailable:
        raise
    except Exception as exc:
        # No provider exception content (URLs/tokens) reaches the API.
        raise PaperDataUnavailable("minute_provider_unavailable" if interval == "1m" else "daily_provider_unavailable") from exc
