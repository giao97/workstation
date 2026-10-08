"""Manual research journal contract. No order, quantity or budget fields."""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AllocationReviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_key: str = Field(min_length=1, max_length=64)
    expected_plan_version: int = Field(ge=1)
    expected_previous_id: int | None = Field(default=None, gt=0)
    target_key: str = Field(min_length=1, max_length=64)
    horizon: Literal["long_term", "tactical"]
    decision: Literal["maintain_plan", "wait", "data_required", "pause"]
    reason: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=4000, description="What changed or remains missing; manually supplied, not independently verified")
    next_condition: str = Field(min_length=1, max_length=2000)
    review_due_at: datetime

    @field_validator("review_due_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review_due_at requires an explicit timezone")
        return value.astimezone(timezone.utc)


class AllocationReviewItem(AllocationReviewWrite):
    id: int
    plan_id: int
    revision: int
    created_at: datetime
    target_snapshot: dict[str, Any]
    authority: Literal["manual_unverified"] = "manual_unverified"
    state: Literal["active", "due", "plan_changed", "plan_inactive"]


class AllocationReviewList(BaseModel):
    plan_version: int
    latest: list[AllocationReviewItem] = Field(default_factory=list)
    items: list[AllocationReviewItem] = Field(default_factory=list)
    next_before_id: int | None = None
