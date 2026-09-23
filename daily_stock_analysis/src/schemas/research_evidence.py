# -*- coding: utf-8 -*-
"""Versioned evidence contract for point-in-time investment research."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVIDENCE_CONTRACT_VERSION = "1.0"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class EvidenceSourceTier(str, Enum):
    """Trust tier used when evidence conflicts."""

    PRIMARY = "primary"
    STRUCTURED_SECONDARY = "structured_secondary"
    SECONDARY = "secondary"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class EvidenceRecord(BaseModel):
    """One traceable evidence item available to a research run."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    stock_code: str = Field(min_length=1)
    market: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_type: str = Field(default="structured_data", min_length=1)
    source_tier: EvidenceSourceTier = EvidenceSourceTier.UNKNOWN
    result: str = Field(default="ok", min_length=1)
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    effective_at: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    report_period: Optional[str] = None
    filing_version: Optional[str] = None
    content_hash: Optional[str] = None
    raw_snapshot_ref: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at", "effective_at", "retrieved_at")
    @classmethod
    def _timestamps_are_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _as_utc(value) if value is not None else None

    @property
    def available_at(self) -> datetime:
        """Earliest defensible availability time for point-in-time use."""
        return self.published_at or self.retrieved_at

    def is_available_at(self, as_of: datetime) -> bool:
        return self.available_at <= _as_utc(as_of)


class EvidenceSnapshot(BaseModel):
    """Evidence frozen for one stock at one research cutoff."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = EVIDENCE_CONTRACT_VERSION
    stock_code: str = Field(min_length=1)
    market: str = Field(min_length=1)
    as_of: datetime
    point_in_time_status: Literal["verified", "limited", "unsafe"] = "limited"
    records: List[EvidenceRecord] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _as_of_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def _reject_future_evidence(self) -> "EvidenceSnapshot":
        future_ids = [record.evidence_id for record in self.records if not record.is_available_at(self.as_of)]
        if future_ids:
            raise ValueError(f"evidence is not available at as_of: {', '.join(future_ids)}")
        return self
