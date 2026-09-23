# -*- coding: utf-8 -*-
"""Pure financial-quality calculations for normalized reporting periods."""

from __future__ import annotations

from typing import Iterable, List, Optional

from src.schemas.financial_research import FinancialPeriod, FinancialQualityMetrics


def _round(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100.0


def _growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100.0


def compute_financial_quality(periods: Iterable[FinancialPeriod]) -> FinancialQualityMetrics:
    """Compute reproducible metrics without inventing missing values."""
    ordered: List[FinancialPeriod] = sorted(periods, key=lambda item: item.period_end, reverse=True)
    if not ordered:
        return FinancialQualityMetrics(completeness_pct=0.0, flags=["financial_periods_missing"])

    latest = ordered[0]
    previous = next(
        (
            period
            for period in ordered[1:]
            if period.period_type == latest.period_type or latest.period_type == "unknown"
        ),
        None,
    )

    gross_margin = _ratio(latest.gross_profit, latest.revenue)
    operating_margin = _ratio(latest.operating_income, latest.revenue)
    net_margin = _ratio(latest.net_profit_parent, latest.revenue)
    cash_conversion = _ratio(latest.operating_cash_flow, latest.net_profit_parent)
    debt_to_assets = _ratio(latest.total_debt, latest.total_assets)
    free_cash_flow = None
    if latest.operating_cash_flow is not None and latest.capital_expenditure is not None:
        free_cash_flow = latest.operating_cash_flow - abs(latest.capital_expenditure)

    revenue_growth = _growth(
        latest.revenue,
        previous.revenue if previous is not None else None,
    )
    profit_growth = _growth(
        latest.net_profit_parent,
        previous.net_profit_parent if previous is not None else None,
    )

    core_values = (
        latest.revenue,
        latest.gross_profit,
        latest.operating_income,
        latest.net_profit_parent,
        latest.operating_cash_flow,
        latest.capital_expenditure,
        latest.total_assets,
        latest.total_equity,
        latest.total_debt,
        latest.cash_and_equivalents,
        latest.basic_eps,
        latest.roe_pct,
    )
    completeness = sum(value is not None for value in core_values) / len(core_values) * 100.0

    flags: List[str] = []
    if latest.net_profit_parent is not None and latest.net_profit_parent > 0:
        if latest.operating_cash_flow is not None and latest.operating_cash_flow < 0:
            flags.append("positive_profit_negative_operating_cash_flow")
        elif cash_conversion is not None and cash_conversion < 70:
            flags.append("weak_cash_conversion")
    if debt_to_assets is not None and debt_to_assets > 70:
        flags.append("high_debt_to_assets")
    if gross_margin is not None and gross_margin < 0:
        flags.append("negative_gross_margin")
    if revenue_growth is not None and revenue_growth < -10:
        flags.append("revenue_decline")
    if profit_growth is not None and profit_growth < -10:
        flags.append("net_profit_decline")

    formulas = {
        "gross_margin_pct": "gross_profit / revenue * 100",
        "operating_margin_pct": "operating_income / revenue * 100",
        "net_margin_pct": "net_profit_parent / revenue * 100",
        "cash_conversion_pct": "operating_cash_flow / net_profit_parent * 100",
        "debt_to_assets_pct": "total_debt / total_assets * 100",
        "free_cash_flow": "operating_cash_flow - abs(capital_expenditure)",
        "growth_pct": "(current - previous) / abs(previous) * 100",
    }

    return FinancialQualityMetrics(
        gross_margin_pct=_round(gross_margin),
        operating_margin_pct=_round(operating_margin),
        net_margin_pct=_round(net_margin),
        cash_conversion_pct=_round(cash_conversion),
        debt_to_assets_pct=_round(debt_to_assets),
        free_cash_flow=_round(free_cash_flow),
        revenue_growth_pct=_round(revenue_growth),
        net_profit_growth_pct=_round(profit_growth),
        completeness_pct=round(completeness, 2),
        flags=flags,
        formulas=formulas,
    )
