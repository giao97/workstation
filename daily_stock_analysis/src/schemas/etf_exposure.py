"""Explicit, reviewed long-only composition inputs; no inferred fund weights."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.core.market_events import safe_url


class Constituent(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    market: str = Field(pattern=r'^[a-z]{2,12}$')
    symbol: str = Field(pattern=r'^[A-Z0-9][A-Z0-9.\-]{0,23}$')
    name: str = Field(min_length=1, max_length=200)
    kind: Literal['equity', 'fund', 'cash', 'other']
    weight_pct: Decimal = Field(gt=0, le=100, max_digits=12, decimal_places=8)


class EtfCompositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    fund_symbol: str = Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,15}$')
    fund_market: Literal['us'] = 'us'
    holdings_as_of: date
    source_url: str = Field(min_length=1, max_length=2000)
    source_name: str = Field(min_length=1, max_length=200)
    source_published_at: datetime | None = None
    methodology: Literal['long_only_nav_weight_pct']
    constituents: list[Constituent] = Field(min_length=1, max_length=3000)

    @field_validator('source_url')
    @classmethod
    def public_link(cls, value):
        cleaned = safe_url(value)
        if not cleaned or cleaned != value:
            raise ValueError('Use a clean public source URL without credentials, tracking or fragments')
        return value

    @field_validator('source_published_at')
    @classmethod
    def zoned_time(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Source publication time requires an explicit timezone')
        return value

    @model_validator(mode='after')
    def weights_and_identities(self):
        identities = [(c.market, c.symbol) for c in self.constituents]
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate market/symbol; reconcile source rows explicitly')
        if any((c.market, c.symbol) == (self.fund_market, self.fund_symbol) for c in self.constituents):
            raise ValueError('Fund cannot contain itself')
        if sum(c.weight_pct for c in self.constituents) > 100:
            raise ValueError('NAV weights exceed 100%; no automatic normalization is allowed')
        return self


class EtfCompositionCommit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot: EtfCompositionInput
    source_reviewed: Literal[True]

    @field_validator('source_reviewed', mode='before')
    @classmethod
    def explicit_review(cls, value):
        if value is not True:
            raise ValueError('Explicit source review is required')
        return value
