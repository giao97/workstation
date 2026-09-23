"""
Standard market-data normalization helpers.

All fetchers should produce the same lowercase OHLCV schema before analysis.
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd


logger = logging.getLogger("quant_trading")


REQUIRED_OHLCV_COLUMNS = ("date", "open", "high", "low", "close")
NUMERIC_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


_COLUMN_ALIASES = {
    "date": "date",
    "datetime": "date",
    "trade_date": "date",
    "datadate": "date",
    "日期": "date",
    "时间": "date",
    "交易日期": "date",
    "open": "open",
    "开盘": "open",
    "今开": "open",
    "high": "high",
    "最高": "high",
    "low": "low",
    "最低": "low",
    "close": "close",
    "收盘": "close",
    "volume": "volume",
    "成交量": "volume",
    "amount": "amount",
    "成交额": "amount",
    "amplitude": "amplitude",
    "振幅": "amplitude",
    "change_pct": "change_pct",
    "涨跌幅": "change_pct",
    "change": "change",
    "涨跌额": "change",
    "turnover": "turnover",
    "换手率": "turnover",
    "adj_close": "adj_close",
    "adjclose": "adj_close",
}


def _canonical_column(value: object) -> str:
    text = str(value).strip().lower()
    return text.replace(" ", "_").replace("-", "_")


def normalize_ohlcv(df: pd.DataFrame, symbol: str = "", source: str = "") -> pd.DataFrame:
    """Normalize AKShare, yfinance, or stored data into one sorted OHLCV schema."""
    if df is None:
        return _empty_ohlcv()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("normalize_ohlcv expects a pandas DataFrame")

    frame = df.copy()
    if frame.empty:
        return _empty_ohlcv()

    # yfinance's reset_index() can leave a synthetic integer index column.
    if "index" in frame.columns and _canonical_column(frame.columns[0]) == "index":
        frame = frame.drop(columns=["index"])

    rename_map: Dict[object, str] = {}
    for column in frame.columns:
        alias = _COLUMN_ALIASES.get(column)
        if alias is None:
            alias = _COLUMN_ALIASES.get(_canonical_column(column))
        if alias:
            rename_map[column] = alias
    frame = frame.rename(columns=rename_map)

    if "date" not in frame.columns:
        logger.warning("%s%s 数据缺少日期列", symbol or "行情", f" ({source})" if source else "")
        return _empty_ohlcv()

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date"])

    for column in NUMERIC_OHLCV_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    missing_required = [column for column in ("open", "high", "low", "close") if column not in frame.columns]
    if missing_required:
        logger.warning("%s%s 缺少行情列: %s", symbol or "行情", f" ({source})" if source else "", ", ".join(missing_required))
        return _empty_ohlcv()

    frame = frame.dropna(subset=["open", "high", "low", "close"], how="all")
    frame = frame.loc[
        frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
    ].copy()
    frame["volume"] = frame["volume"].fillna(0)
    frame["volume"] = frame["volume"].clip(lower=0)

    for column in ("amount", "amplitude", "change_pct", "change", "turnover", "adj_close"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.sort_values("date")
    frame = frame.drop_duplicates(subset=["date"], keep="last")
    return frame.reset_index(drop=True)


def _empty_ohlcv() -> pd.DataFrame:
    columns = list(REQUIRED_OHLCV_COLUMNS) + ["volume"]
    return pd.DataFrame({column: pd.Series(dtype="float64" if column != "date" else "datetime64[ns]") for column in columns})


def summarize_ohlcv_quality(df: pd.DataFrame) -> Dict[str, object]:
    """Return basic completeness metadata for one normalized market series."""
    frame = normalize_ohlcv(df)
    if frame.empty:
        return {
            "rows": 0,
            "latest_date": None,
            "days_covered": 0,
            "required_columns": 0,
            "required_column_ratio": 0.0,
        }

    required_count = sum(column in frame.columns for column in REQUIRED_OHLCV_COLUMNS)
    latest = frame["date"].max()
    days_covered = int((frame["date"].max() - frame["date"].min()).days + 1)
    return {
        "rows": int(len(frame)),
        "latest_date": latest.strftime("%Y-%m-%d") if pd.notna(latest) else None,
        "days_covered": days_covered,
        "required_columns": required_count,
        "required_column_ratio": round(required_count / len(REQUIRED_OHLCV_COLUMNS), 3),
    }
