# -*- coding: utf-8 -*-
"""Fixed Standard stock research report contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


STANDARD_REPORT_CONTRACT_VERSION = "1.0"


class StandardReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: Literal[
        "investment_conclusion", "company_overview", "business_model",
        "industry_competition", "financial_quality", "peer_comparison",
        "valuation", "events", "historical_analogs", "probability_outlook",
        "conditional_action", "risks_countercase", "data_evidence",
    ]
    title: str
    status: Literal["available", "limited", "missing"]
    facts: Dict[str, Any] = Field(default_factory=dict)
    evidence_ids: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    narrative: Optional[str] = None


class StandardStockReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = STANDARD_REPORT_CONTRACT_VERSION
    report_type: Literal["standard"] = "standard"
    stock_code: str
    market: str
    as_of: datetime
    status: Literal["complete", "partial", "insufficient"]
    research_stance: Literal["constructive", "neutral", "cautious", "avoid", "insufficient"] = "insufficient"
    confidence_pct: float = Field(default=0.0, ge=0, le=100)
    sections: List[StandardReportSection]
    disclosures: List[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

