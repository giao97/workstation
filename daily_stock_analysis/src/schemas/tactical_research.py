"""Explicit what-if inputs. These are not cash confirmations or trade intents."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TacticalLot(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    symbol: str = Field(min_length=1, max_length=16, pattern=r'^[A-Z0-9.^-]+$')
    investment_usd: float = Field(gt=0, le=10_000_000)
    planned_loss_pct: float = Field(gt=0, lt=100)
    round_trip_cost_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    thesis: str = Field(min_length=3, max_length=500)
    invalidation: str = Field(min_length=3, max_length=500)


class TacticalPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    available_cash_usd: float = Field(ge=0, le=10_000_000)
    cash_as_of: datetime
    cash_net_of_other_budgets: bool
    loss_tolerance_pct: float = Field(gt=0, lt=100)
    lots: list[TacticalLot] = Field(min_length=1, max_length=10)

    @field_validator('cash_as_of')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Cash timestamp requires timezone')
        return value
