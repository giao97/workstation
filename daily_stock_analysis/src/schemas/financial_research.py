# -*- coding: utf-8 -*-
"""Normalized multi-period financial research contract."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.research_evidence import EvidenceSnapshot


FINANCIAL_RESEARCH_CONTRACT_VERSION = "1.0"


class FinancialPeriod(BaseModel):
    """Comparable financial values for one disclosed reporting period."""

    model_config = ConfigDict(extra="forbid")

    period_end: date
    period_type: Literal["annual", "quarterly", "interim", "ttm", "unknown"] = "unknown"
    currency: Optional[str] = None
    provider: Optional[str] = None
    filing_version: Optional[str] = None
    source_url: Optional[str] = None
    raw_snapshot_ref: Optional[str] = None
    published_at: Optional[datetime] = None
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_profit_parent: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None
    total_assets: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    basic_eps: Optional[float] = None
    roe_pct: Optional[float] = None
    evidence_ids: List[str] = Field(default_factory=list)

    @field_validator("published_at")
    @classmethod
    def _published_at_is_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator(
        "revenue",
        "gross_profit",
        "operating_income",
        "net_profit_parent",
        "operating_cash_flow",
        "capital_expenditure",
        "total_assets",
        "total_equity",
        "total_debt",
        "cash_and_equivalents",
        "basic_eps",
        "roe_pct",
    )
    @classmethod
    def _numbers_are_finite(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("financial values must be finite")
        return value


class FinancialQualityMetrics(BaseModel):
    """Deterministically derived financial quality metrics."""

    model_config = ConfigDict(extra="forbid")

    gross_margin_pct: Optional[float] = None
    operating_margin_pct: Optional[float] = None
    net_margin_pct: Optional[float] = None
    cash_conversion_pct: Optional[float] = None
    debt_to_assets_pct: Optional[float] = None
    free_cash_flow: Optional[float] = None
    revenue_growth_pct: Optional[float] = None
    net_profit_growth_pct: Optional[float] = None
    completeness_pct: float = Field(ge=0, le=100)
    flags: List[str] = Field(default_factory=list)
    formulas: Dict[str, str] = Field(default_factory=dict)


class FundamentalResearchContract(BaseModel):
    """Versioned, report-ready fundamental research payload."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = FINANCIAL_RESEARCH_CONTRACT_VERSION
    stock_code: str = Field(min_length=1)
    market: str = Field(min_length=1)
    as_of: datetime
    evidence: EvidenceSnapshot
    periods: List[FinancialPeriod] = Field(default_factory=list)
    quality: FinancialQualityMetrics
    warnings: List[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _as_of_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _periods_respect_cutoff(self) -> "FundamentalResearchContract":
        future_periods = [
            period.period_end.isoformat()
            for period in self.periods
            if period.published_at is not None and period.published_at > self.as_of
        ]
        if future_periods:
            raise ValueError(f"financial periods were not published at as_of: {', '.join(future_periods)}")
        return self
