"""Strict input/model contracts for the market-event research workflow."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.market_events import publication, safe_url


class ManualNews(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default='', max_length=2000)
    url: str = Field(default='', max_length=2000)
    source: str = Field(default='user supplied', min_length=1, max_length=100)
    published_at: str = Field(default='', max_length=100)
    event_at: str = Field(default='', max_length=100)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if value and not safe_url(value):
            raise ValueError('Use a public HTTP(S) source link without credentials')
        return value

    @field_validator('event_at')
    @classmethod
    def aware_event_time(cls, value):
        if value and publication(value)[1] != 'timestamp':
            raise ValueError('Event time must include a timezone')
        return value


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    market: Literal['cn', 'hk', 'us', 'global'] = 'cn'
    language: Literal['zh', 'en'] = 'zh'
    refresh_sources: bool = False
    search_news: bool = True
    scan_sectors: bool = True
    analyze: bool = True
    manual_items: list[ManualNews] = Field(default_factory=list, max_length=5)


class AnalysisRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class HoldingLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(min_length=1, max_length=16)
    market: str = Field(min_length=1, max_length=16)
    reason: str = Field(min_length=1, max_length=400)


class EventInterpretation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_key: str
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    transmission: str = Field(min_length=1, max_length=700)
    beneficiaries: str = Field(min_length=1, max_length=400)
    risks: str = Field(min_length=1, max_length=400)
    countercase: str = Field(min_length=1, max_length=500)
    horizon: str = Field(min_length=1, max_length=120)
    confirmation: str = Field(min_length=1, max_length=500)
    invalidation: str = Field(min_length=1, max_length=500)
    holding_links: list[HoldingLink] = Field(default_factory=list, max_length=50)


class InterpretationBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    events: list[EventInterpretation] = Field(max_length=8)


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    status: Literal['confirmed', 'disputed', 'retracted', 'unverified']
    evidence_url: str = Field(min_length=1, max_length=2000)
    note: str = Field(min_length=10, max_length=1000)

    @field_validator('evidence_url')
    @classmethod
    def valid_url(cls, value):
        result = safe_url(value)
        if not result:
            raise ValueError('A public supporting/correction source URL is required')
        return result
