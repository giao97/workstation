"""Data completeness and confidence helpers for report consumers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from src.data.schema import summarize_ohlcv_quality


A_SHARE_FIELDS = (
    "pe_ttm",
    "pb",
    "roe",
    "gross_margin",
    "net_margin",
    "revenue_growth",
    "net_profit_growth",
    "debt_ratio",
    "operating_cashflow",
)

US_FIELDS = (
    "pe_ratio",
    "forward_pe",
    "pb_ratio",
    "roe",
    "revenue_growth",
    "earnings_growth",
    "profit_margins",
    "debt_to_equity",
    "free_cashflow",
)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        return bool(pd.notna(value))
    except (TypeError, ValueError):
        return True


def analyze_data_quality(
    market_df: pd.DataFrame,
    fundamental: Optional[Dict[str, Any]] = None,
    market: str = "",
) -> Dict[str, Any]:
    """Combine OHLCV and fundamental completeness into a bounded confidence score."""
    ohlcv_quality = summarize_ohlcv_quality(market_df)
    raw = fundamental or {}
    required_fields = A_SHARE_FIELDS if market and market.startswith("A") else US_FIELDS
    present_fields = [field for field in required_fields if _has_value(raw.get(field))]
    field_ratio = len(present_fields) / len(required_fields) if required_fields else 0.0

    latest_date = ohlcv_quality.get("latest_date")
    try:
        age_days = (datetime.now().date() - pd.Timestamp(latest_date).date()).days if latest_date else None
    except (TypeError, ValueError):
        age_days = None

    score = round(
        ohlcv_quality.get("required_column_ratio", 0.0) * 45
        + field_ratio * 40
        + max(0, 15 - (age_days or 30) / 2),
        1,
    )
    score = max(0.0, min(100.0, score))

    if score >= 80:
        confidence = "HIGH"
    elif score >= 55:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    reasons = []
    if ohlcv_quality.get("rows", 0) < 120:
        reasons.append("历史数据不足120个交易日")
    if field_ratio < 0.6:
        reasons.append("基本面字段覆盖不足")
    if age_days is None:
        reasons.append("缺少最新行情日期")
    elif age_days > 7:
        reasons.append(f"最新行情已滞后{age_days}天")

    return {
        "confidence": confidence,
        "score": score,
        "ohlcv": ohlcv_quality,
        "fundamental_field_ratio": round(field_ratio, 3),
        "fundamental_fields_present": len(present_fields),
        "fundamental_fields_required": len(required_fields),
        "issues": reasons[:4],
    }
