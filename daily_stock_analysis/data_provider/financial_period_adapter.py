# -*- coding: utf-8 -*-
"""Cross-market financial-statement normalization helpers.

The functions in this module are deterministic and network-free.  Provider
adapters remain responsible for fetching raw statements; this module only
maps disclosed fields into the repo-wide ``financial_periods`` contract.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd


FIELD_ALIASES: Dict[str, Sequence[str]] = {
    "revenue": ("营业总收入", "营业收入", "营业额", "Total Revenue", "TotalRevenue", "Revenue"),
    "gross_profit": ("毛利", "毛利润", "Gross Profit", "GrossProfit"),
    "operating_income": ("营业利润", "经营利润", "Operating Income", "OperatingIncome"),
    "net_profit_parent": (
        "归属母公司净利润", "归母净利润", "归属普通股股东净利润", "净利润",
        "Net Income Common Stockholders", "Net Income", "NetIncome",
    ),
    "operating_cash_flow": (
        "经营活动产生的现金流量净额", "经营现金流", "经营活动现金流",
        "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
        "Total Cash From Operating Activities",
    ),
    "capital_expenditure": ("资本开支", "资本性支出", "Capital Expenditure", "CapitalExpenditure"),
    "total_assets": ("资产总计", "总资产", "Total Assets", "TotalAssets"),
    "total_equity": (
        "归属于母公司股东权益合计", "股东权益合计", "所有者权益合计",
        "Stockholders Equity", "Total Equity Gross Minority Interest", "TotalEquity",
    ),
    "total_debt": ("总债务", "有息负债", "Total Debt", "TotalDebt"),
    "cash_and_equivalents": (
        "货币资金", "现金及现金等价物", "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents", "CashCashEquivalentsAndShortTermInvestments",
    ),
    "basic_eps": ("基本每股收益", "Basic EPS", "BasicEPS"),
    "roe": ("净资产收益率", "ROE", "Return On Equity"),
}


def safe_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "N/A", "nan", "None"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def iso_date(value: Any) -> Optional[str]:
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def iso_datetime(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().astimezone(timezone.utc).isoformat()


def infer_period_type(period_end: str, label: Any = None) -> str:
    text = str(label or "").lower()
    if any(token in text for token in ("annual", "year", "fy", "年度", "年报")):
        return "annual"
    if any(token in text for token in ("quarter", "q1", "q2", "q3", "q4", "季度", "季报")):
        return "quarterly"
    if any(token in text for token in ("half", "interim", "半年", "中期")):
        return "interim"
    parsed = date.fromisoformat(period_end)
    return "annual" if (parsed.month, parsed.day) == (12, 31) else "quarterly"


def _matching_value(values: Mapping[str, Any], field: str) -> Optional[float]:
    aliases = FIELD_ALIASES[field]
    for alias in aliases:
        if alias in values:
            number = safe_number(values.get(alias))
            if number is not None:
                return number
    for key, value in values.items():
        normalized = str(key).strip().lower().replace("_", " ")
        for alias in aliases:
            candidate = alias.lower().replace("_", " ")
            if candidate == normalized or candidate in normalized:
                number = safe_number(value)
                if number is not None:
                    return number
    return None


def normalize_statement_frames(
    *,
    income: Optional[pd.DataFrame],
    balance_sheet: Optional[pd.DataFrame],
    cash_flow: Optional[pd.DataFrame],
    currency: Optional[str],
    provider: str = "yfinance",
    period_type: str = "quarterly",
    max_periods: int = 12,
) -> List[Dict[str, Any]]:
    """Normalize yfinance-style frames whose columns are reporting dates."""
    frames = [frame for frame in (income, balance_sheet, cash_flow) if isinstance(frame, pd.DataFrame) and not frame.empty]
    dates = sorted(
        {iso_date(column) for frame in frames for column in frame.columns if iso_date(column)},
        reverse=True,
    )
    periods: List[Dict[str, Any]] = []
    for period_end in dates[:max_periods]:
        values: Dict[str, Any] = {}
        for frame in frames:
            for column in frame.columns:
                if iso_date(column) != period_end:
                    continue
                for row_name, raw in frame[column].items():
                    values[str(row_name)] = raw
        payload: Dict[str, Any] = {
            "report_date": period_end,
            "period": period_type,
            "currency": currency,
            "provider": provider,
            "published_at": None,
        }
        for field in FIELD_ALIASES:
            payload[field] = _matching_value(values, field)
        if any(payload.get(field) is not None for field in FIELD_ALIASES):
            periods.append(payload)
    return periods


def normalize_futu_reports(
    statements: Mapping[str, Mapping[str, Any]],
    *,
    max_periods: int = 12,
) -> List[Dict[str, Any]]:
    """Join Futu report_list payloads by reporting date."""
    joined: Dict[str, Dict[str, Any]] = {}
    for statement in statements.values():
        for report in statement.get("report_list") or []:
            if not isinstance(report, dict):
                continue
            period_end = iso_date(report.get("date_time_str") or report.get("report_date"))
            if not period_end:
                continue
            target = joined.setdefault(period_end, {})
            target.setdefault("period", report.get("period_text"))
            target.setdefault("currency", report.get("currency_code") or report.get("currency_info"))
            target.setdefault(
                "published_at",
                iso_datetime(report.get("publish_date") or report.get("announcement_date") or report.get("filing_date")),
            )
            for item in report.get("item_list") or []:
                if isinstance(item, dict) and item.get("display_name"):
                    target[str(item["display_name"])] = item.get("data")

    periods: List[Dict[str, Any]] = []
    for period_end in sorted(joined, reverse=True)[:max_periods]:
        raw = joined[period_end]
        payload: Dict[str, Any] = {
            "report_date": period_end,
            "period": infer_period_type(period_end, raw.get("period")),
            "currency": raw.get("currency"),
            "provider": "futu",
            "published_at": raw.get("published_at"),
        }
        for field in FIELD_ALIASES:
            payload[field] = _matching_value(raw, field)
        if any(payload.get(field) is not None for field in FIELD_ALIASES):
            periods.append(payload)
    return periods


def normalize_akshare_financials(
    frame: Optional[pd.DataFrame],
    *,
    currency: str = "CNY",
    provider: str = "akshare",
    max_periods: int = 12,
) -> List[Dict[str, Any]]:
    """Normalize both common AkShare financial-abstract layouts."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []

    # Layout A: one indicator per row, reporting dates across columns.
    date_columns = [column for column in frame.columns if iso_date(column)]
    label_columns = [column for column in frame.columns if str(column) in {"指标", "选项", "项目", "item", "指标名称"}]
    if date_columns and label_columns:
        label_column = label_columns[-1]
        transposed: Dict[str, Dict[str, Any]] = {}
        for column in date_columns:
            period_end = iso_date(column)
            if not period_end:
                continue
            values = {
                str(row[label_column]): row[column]
                for _, row in frame.iterrows()
                if row.get(label_column) not in (None, "")
            }
            transposed[period_end] = values
        periods = []
        for period_end in sorted(transposed, reverse=True)[:max_periods]:
            payload: Dict[str, Any] = {
                "report_date": period_end,
                "period": infer_period_type(period_end),
                "currency": currency,
                "provider": provider,
                "published_at": None,
            }
            for field in FIELD_ALIASES:
                payload[field] = _matching_value(transposed[period_end], field)
            if any(payload.get(field) is not None for field in FIELD_ALIASES):
                periods.append(payload)
        return periods

    # Layout B: one period per row.
    periods = []
    for _, row in frame.iterrows():
        values = {str(key): value for key, value in row.items()}
        report_value = next(
            (value for key, value in values.items() if any(token in key for token in ("报告期", "报告日期", "截止日期", "date"))),
            None,
        )
        period_end = iso_date(report_value)
        if not period_end:
            continue
        published_value = next(
            (value for key, value in values.items() if any(token in key for token in ("公告日期", "披露日期", "publish", "filing"))),
            None,
        )
        payload = {
            "report_date": period_end,
            "period": infer_period_type(period_end, values.get("报告类型")),
            "currency": currency,
            "provider": provider,
            "published_at": iso_datetime(published_value),
        }
        for field in FIELD_ALIASES:
            payload[field] = _matching_value(values, field)
        if any(payload.get(field) is not None for field in FIELD_ALIASES):
            periods.append(payload)
    periods.sort(key=lambda item: item["report_date"], reverse=True)
    return periods[:max_periods]
