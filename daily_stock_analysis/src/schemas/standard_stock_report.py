# -*- coding: utf-8 -*-
"""Fixed Standard stock research report contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


STANDARD_REPORT_CONTRACT_VERSION = "1.1"


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

    contract_version: Literal["1.1"] = STANDARD_REPORT_CONTRACT_VERSION
    report_type: Literal["standard"] = "standard"
    stock_code: str
    market: str
    as_of: datetime
    status: Literal["complete", "partial", "insufficient"]
    research_stance: Literal["constructive", "neutral", "cautious", "avoid", "insufficient"] = "insufficient"
    coverage_pct: float = Field(default=0.0, ge=0, le=100, description="Non-missing section percentage, including limited sections; not confidence or win probability")
    confidence_pct: None = Field(default=None, deprecated=True, description="Uncalibrated: always null. Use coverage_pct for section coverage.")
    sections: List[StandardReportSection]
    disclosures: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _read_legacy_coverage(cls, value: Any) -> Any:
        # v1.0 mislabeled section coverage as confidence. Normalize only on read;
        # never rewrite archived reports or reinterpret it as model confidence.
        if isinstance(value, dict) and (value.get("contract_version") == "1.0" or (
            "contract_version" not in value and isinstance(value.get("confidence_pct"), (int, float))
        )):
            value = dict(value)
            legacy = value.pop("confidence_pct", None)
            value.setdefault("coverage_pct", legacy if legacy is not None else 0.0)
            value["contract_version"] = STANDARD_REPORT_CONTRACT_VERSION
            value["disclosures"] = list(value.get("disclosures", [])) + [
                "旧版 confidence_pct 是章节覆盖率，已按 coverage_pct 读取；并非置信度或胜率。"
            ]
        return value

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
