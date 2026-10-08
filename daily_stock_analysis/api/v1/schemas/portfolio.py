# -*- coding: utf-8 -*-
"""Portfolio API schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError
from src.schemas.allocation_review import AllocationReviewItem


class PortfolioProfilePreviewRequest(BaseModel):
    document: str = Field(..., min_length=1, max_length=128 * 1024)


class PortfolioAccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    broker: Optional[str] = Field(None, max_length=64)
    market: Literal["cn", "hk", "us", "jp", "kr", "tw"] = "cn"
    base_currency: str = Field("CNY", min_length=3, max_length=8)
    owner_id: Optional[str] = Field(None, max_length=64)


class PortfolioAccountUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    broker: Optional[str] = Field(None, max_length=64)
    market: Optional[Literal["cn", "hk", "us", "jp", "kr", "tw"]] = None
    base_currency: Optional[str] = Field(None, min_length=3, max_length=8)
    owner_id: Optional[str] = Field(None, max_length=64)
    is_active: Optional[bool] = None


class PortfolioAccountItem(BaseModel):
    id: int
    owner_id: Optional[str] = None
    name: str
    broker: Optional[str] = None
    market: str
    base_currency: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PortfolioAccountListResponse(BaseModel):
    accounts: List[PortfolioAccountItem] = Field(default_factory=list)


class PortfolioOpeningPosition(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    quantity: float = Field(..., gt=0, allow_inf_nan=False)
    avg_cost: float = Field(..., ge=0, allow_inf_nan=False)
    reported_market_value: Optional[float] = Field(None, ge=0, allow_inf_nan=False)


class PortfolioOpeningRequest(BaseModel):
    as_of: date
    positions: List[PortfolioOpeningPosition] = Field(..., min_length=1, max_length=1000)
    cash_balance: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    reported_market_value: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    reported_equity: Optional[float] = Field(None, ge=0, allow_inf_nan=False)


class PortfolioOpeningCommitRequest(PortfolioOpeningRequest):
    confirmed: Literal[True]
    preview_token: str = Field(..., min_length=64, max_length=64)


class PortfolioOpeningPreview(BaseModel):
    account_id: int
    opening: Dict[str, Any]
    preview_token: str
    can_commit: bool
    detail_market_value: Optional[float] = None
    market_value_difference: Optional[float] = None
    equity_less_market_value: Optional[float] = None
    equity_difference: Optional[float] = None
    limitations: List[str] = Field(default_factory=list)


class PortfolioOpeningCommitResponse(BaseModel):
    account_id: int
    created: bool


class PortfolioFundingRequest(BaseModel):
    as_of: date
    settled_cash: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    available_cash: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    planned_deposit: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    planned_deposit_date: Optional[date] = None


class PortfolioAccountStateResponse(BaseModel):
    account_id: int
    currency: str
    opening: Optional[Dict[str, Any]] = None
    funding: Optional[Dict[str, Any]] = None
    cash_confirmed: bool
    confirmed_cash_cap: Optional[float] = None
    disclosures: List[str] = Field(default_factory=list)


class PortfolioTradeCreateRequest(BaseModel):
    request_key: Optional[str] = Field(None, min_length=1, max_length=128)
    account_id: int
    symbol: str = Field(..., min_length=1, max_length=16)
    trade_date: date
    side: Literal["buy", "sell"]
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    fee: float = Field(0.0, ge=0)
    tax: float = Field(0.0, ge=0)
    market: Optional[Literal["cn", "hk", "us", "jp", "kr", "tw"]] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=8)
    trade_uid: Optional[str] = Field(None, max_length=128)
    note: Optional[str] = Field(None, max_length=255)
    executed_at: Optional[datetime] = None
    fee_status: Literal['unknown', 'estimated', 'confirmed'] = 'unknown'
    price_basis: Literal['execution'] = 'execution'
    intent_id: Optional[int] = Field(None, gt=0)

    @model_validator(mode='after')
    def confirmed_costs_are_explicit(self):
        if self.fee_status == 'confirmed' and not {'fee', 'tax'} <= self.model_fields_set:
            raise PydanticCustomError(
                'confirmed_costs_required',
                'Confirmed costs require explicit fee and tax, including verified zeros',
            )
        return self


class PortfolioTradeReconcileRequest(BaseModel):
    expected_revision: int = Field(..., ge=1)
    executed_at: Optional[datetime] = None
    fee: float = Field(..., ge=0, allow_inf_nan=False)
    tax: float = Field(..., ge=0, allow_inf_nan=False)
    fee_status: Literal['unknown', 'estimated', 'confirmed']
    reason: str = Field(..., min_length=1, max_length=255, pattern=r'\S')


class PortfolioBudgetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r'\S')
    currency: str = Field(..., min_length=3, max_length=8)
    timezone: str = Field(..., max_length=64)
    start_date: date
    end_date: date
    amount: float = Field(..., gt=0, allow_inf_nan=False)
    symbols: List[str] = Field(..., min_length=1, max_length=100)
    ledger_complete: bool = False
    request_key: str = Field(..., min_length=1, max_length=128, pattern=r'\S')




class PortfolioBudgetConfirmation(BaseModel):
    confirmed: bool


class PortfolioBudgetAdjustment(BaseModel):
    fx_rate: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    excluded: bool = False
    reason: str = Field(..., min_length=1, max_length=255, pattern=r'\S')


class PortfolioIntentRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    quantity: float = Field(..., gt=0, allow_inf_nan=False)
    limit_price: float = Field(..., gt=0, allow_inf_nan=False)
    fee_reserve: float = Field(..., ge=0, allow_inf_nan=False)
    fx_rate: float = Field(..., gt=0, allow_inf_nan=False)
    expires_at: datetime
    request_key: str = Field(..., min_length=1, max_length=128, pattern=r'\S')


class PortfolioIntentStateRequest(BaseModel):
    expected_revision: int = Field(..., ge=1)
    status: Literal['submitted', 'pending_cancel', 'cancelled', 'expired']
    reason: str = Field(..., min_length=1, max_length=255, pattern=r'\S')


class PortfolioPerformanceRequest(BaseModel):
    start_date: date
    end_date: date
    symbols: List[str] = Field(default_factory=list, max_length=50)
    ledger_confirmed: bool = False
    include_realtime: bool = False


class PortfolioCashLedgerCreateRequest(BaseModel):
    account_id: int
    event_date: date
    direction: Literal["in", "out"]
    amount: float = Field(..., gt=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=8)
    note: Optional[str] = Field(None, max_length=255)


class PortfolioCorporateActionCreateRequest(BaseModel):
    account_id: int
    symbol: str = Field(..., min_length=1, max_length=16)
    effective_date: date
    action_type: Literal["cash_dividend", "split_adjustment"]
    market: Optional[Literal["cn", "hk", "us", "jp", "kr", "tw"]] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=8)
    cash_dividend_per_share: Optional[float] = Field(None, ge=0)
    split_ratio: Optional[float] = Field(None, gt=0)
    note: Optional[str] = Field(None, max_length=255)


class PortfolioEventCreatedResponse(BaseModel):
    id: int


class PortfolioDeleteResponse(BaseModel):
    deleted: int


class PortfolioTradeListItem(BaseModel):
    id: int
    account_id: int
    trade_uid: Optional[str] = None
    symbol: str
    market: str
    currency: str
    trade_date: str
    side: str
    quantity: float
    price: float
    fee: float
    tax: float
    note: Optional[str] = None
    created_at: Optional[str] = None
    executed_at: Optional[str] = None
    fee_status: str = 'unknown'
    price_basis: str = 'execution'
    revision: int = 1
    intent_id: Optional[int] = None


class PortfolioTradeListResponse(BaseModel):
    items: List[PortfolioTradeListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class PortfolioCashLedgerListItem(BaseModel):
    id: int
    account_id: int
    event_date: str
    direction: str
    amount: float
    currency: str
    note: Optional[str] = None
    created_at: Optional[str] = None


class PortfolioCashLedgerListResponse(BaseModel):
    items: List[PortfolioCashLedgerListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class PortfolioCorporateActionListItem(BaseModel):
    id: int
    account_id: int
    symbol: str
    market: str
    currency: str
    effective_date: str
    action_type: str
    cash_dividend_per_share: Optional[float] = None
    split_ratio: Optional[float] = None
    note: Optional[str] = None
    created_at: Optional[str] = None


class PortfolioCorporateActionListResponse(BaseModel):
    items: List[PortfolioCorporateActionListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class PortfolioPositionItem(BaseModel):
    symbol: str
    market: str
    currency: str
    quantity: float
    avg_cost: float
    total_cost: float
    last_price: float
    market_value_base: float
    unrealized_pnl_base: float
    unrealized_pnl_pct: Optional[float] = None
    valuation_currency: str
    price_source: str = "unknown"
    price_provider: Optional[str] = None
    price_date: Optional[str] = None
    price_timestamp: Optional[str] = None
    price_fetched_at: Optional[str] = None
    price_stale: bool = False
    price_available: bool = True
    data_quality: str = "ok"
    limitations: List[str] = Field(default_factory=list)


class PortfolioPositionAnalysisRequest(BaseModel):
    account_id: Optional[int] = Field(None, description="Optional account id; required when a symbol is held in multiple accounts")
    analysis_phase: Literal["auto", "premarket", "intraday", "postmarket"] = "auto"
    force: bool = Field(False, description="Force refresh analysis inputs without bypassing duplicate in-flight tasks")


class PortfolioAccountSnapshot(BaseModel):
    account_id: int
    account_name: str
    owner_id: Optional[str] = None
    broker: Optional[str] = None
    market: str
    base_currency: str
    as_of: str
    cost_method: str
    total_cash: float
    funding: Optional[PortfolioAccountStateResponse] = None
    total_market_value: float
    total_equity: float
    realized_pnl: float
    net_pnl_verified: bool = False
    unrealized_pnl: float
    fee_total: float
    tax_total: float
    fx_stale: bool
    data_quality: str = "ok"
    limitations: List[str] = Field(default_factory=list)
    positions: List[PortfolioPositionItem] = Field(default_factory=list)


class PortfolioSnapshotResponse(BaseModel):
    as_of: str
    cost_method: str
    currency: str
    account_count: int
    total_cash: float
    total_market_value: float
    total_equity: float
    realized_pnl: float
    net_pnl_verified: bool = False
    unrealized_pnl: float
    fee_total: float
    tax_total: float
    fx_stale: bool
    data_quality: str = "ok"
    limitations: List[str] = Field(default_factory=list)
    accounts: List[PortfolioAccountSnapshot] = Field(default_factory=list)


class PortfolioImportTradeItem(BaseModel):
    fee_status: Literal['unknown', 'estimated', 'confirmed'] = 'unknown'
    executed_at: Optional[datetime] = None
    price_basis: Literal['execution'] = 'execution'
    trade_date: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    fee: float
    tax: float
    trade_uid: Optional[str] = None
    dedup_hash: str
    currency: Optional[str] = None


class PortfolioImportParseResponse(BaseModel):
    broker: str
    record_count: int
    skipped_count: int
    error_count: int
    records: List[PortfolioImportTradeItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class PortfolioImportCommitResponse(BaseModel):
    account_id: int
    record_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    dry_run: bool
    errors: List[str] = Field(default_factory=list)


class PortfolioImportBrokerItem(BaseModel):
    broker: str
    aliases: List[str] = Field(default_factory=list)
    display_name: Optional[str] = None


class PortfolioImportBrokerListResponse(BaseModel):
    brokers: List[PortfolioImportBrokerItem] = Field(default_factory=list)


class PortfolioFxRefreshResponse(BaseModel):
    as_of: str
    account_count: int
    refresh_enabled: bool
    disabled_reason: Optional[str] = None
    pair_count: int
    updated_count: int
    stale_count: int
    error_count: int


class PortfolioDecisionSignalRiskItem(BaseModel):
    account_id: Optional[int] = None
    symbol: str
    market: str
    signal: Dict[str, Any] = Field(default_factory=dict)


class PortfolioDecisionSignalRiskBlock(BaseModel):
    available: bool = True
    total: int = 0
    actions: Dict[str, int] = Field(default_factory=dict)
    items: List[PortfolioDecisionSignalRiskItem] = Field(default_factory=list)


class PortfolioRiskResponse(BaseModel):
    as_of: str
    account_id: Optional[int] = None
    cost_method: str
    currency: str
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    concentration: Dict[str, Any] = Field(default_factory=dict)
    sector_concentration: Dict[str, Any] = Field(default_factory=dict)
    drawdown: Dict[str, Any] = Field(default_factory=dict)
    stop_loss: Dict[str, Any] = Field(default_factory=dict)
    decision_signal_risk: PortfolioDecisionSignalRiskBlock = Field(default_factory=PortfolioDecisionSignalRiskBlock)


class PortfolioAllocationTargetInput(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=96)
    source: Literal["position", "cash", "manual"] = "position"
    policy: Literal["buy_only", "rebalance", "hold_only", "exit_only"] = "buy_only"
    market: Optional[Literal["cn", "hk", "us", "jp", "kr", "tw"]] = None
    symbols: List[str] = Field(default_factory=list)
    target_pct: float = Field(..., ge=0, le=100)
    min_pct: Optional[float] = Field(None, ge=0, le=100)
    max_pct: Optional[float] = Field(None, ge=0, le=100)
    batch_amount: Optional[float] = Field(None, gt=0)
    current_amount: Optional[float] = Field(None, ge=0)
    sort_order: int = 0
    note: Optional[str] = Field(None, max_length=500)


class PortfolioAllocationPlanWriteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=96)
    owner_id: Optional[str] = Field(None, max_length=64)
    base_currency: str = Field("CNY", min_length=3, max_length=8)
    target_total_value: float = Field(..., gt=0)
    account_id: Optional[int] = Field(None, gt=0, description="Fixed scope; null means all active accounts")
    ledger_complete: bool = Field(False, description="User confirms holdings and cash for this scope are fully recorded")
    cash_reserve_amount: float = Field(0, ge=0)
    include_in_reports: bool = Field(False, description="Include in daily reports sent to existing report recipients")
    targets: List[PortfolioAllocationTargetInput] = Field(..., min_length=1)


class PortfolioAllocationTargetItem(PortfolioAllocationTargetInput):
    id: int


class PortfolioAllocationPlanItem(BaseModel):
    id: int
    owner_id: Optional[str] = None
    name: str
    base_currency: str
    target_total_value: float
    account_id: Optional[int] = None
    ledger_complete: bool = False
    cash_reserve_amount: float = 0
    include_in_reports: bool = False
    version: int
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    targets: List[PortfolioAllocationTargetItem] = Field(default_factory=list)


class PortfolioAllocationPlanSummary(BaseModel):
    id: int
    owner_id: Optional[str] = None
    name: str
    base_currency: str
    target_total_value: float
    account_id: Optional[int] = None
    ledger_complete: bool = False
    cash_reserve_amount: float = 0
    include_in_reports: bool = False
    version: int
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PortfolioAllocationPlanListResponse(BaseModel):
    plans: List[PortfolioAllocationPlanSummary] = Field(default_factory=list)


class PortfolioAllocationMatchedPosition(BaseModel):
    symbol: str
    market: str
    current_amount: float
    price_available: bool
    price_stale: bool = False


class CoreEntryAssessment(BaseModel):
    symbol: Literal['QQQM', 'VOO']
    method: str
    state: Literal['candidate', 'wait', 'risk_review', 'data_required']
    as_of: Optional[str]
    evaluated_at: str
    sources: List[str]
    metrics: Dict[str, float]
    reasons: List[str]
    checks: List[str]
    limitations: List[str]
    executable: Literal[False] = False
    allocation_ready: bool
    allocation_action: str


class PortfolioAllocationTargetStatus(BaseModel):
    key: str
    name: str
    source: str
    policy: str
    market: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    target_pct: float
    target_amount: float
    current_pct: Optional[float] = None
    current_amount: Optional[float] = None
    gap_amount: Optional[float] = None
    min_pct: Optional[float] = None
    max_pct: Optional[float] = None
    batch_amount: Optional[float] = None
    band_status: Literal["below_min", "inside_band", "above_max", "unknown"]
    action: Literal["add", "hold", "reduce", "review"]
    recommended_amount: float
    allocation_cap: float = 0
    funded_amount: Optional[float] = None
    is_estimate: bool = False
    reference_notes: List[str] = Field(default_factory=list)
    reason: str
    data_complete: bool
    limitations: List[str] = Field(default_factory=list)
    matched_positions: List[PortfolioAllocationMatchedPosition] = Field(default_factory=list)
    research_reviews: List[AllocationReviewItem] = Field(default_factory=list)
    core_entries: List[CoreEntryAssessment] = Field(default_factory=list)


class PortfolioAllocationUnassignedPosition(BaseModel):
    symbol: str
    market: str
    current_amount: float
    price_available: bool


class PortfolioAllocationStatusResponse(BaseModel):
    plan_id: int
    plan_name: str
    plan_version: int
    base_currency: str
    target_total_value: float
    as_of: Optional[str] = None
    account_id: Optional[int] = None
    cost_method: str
    include_realtime: bool
    ledger_complete: bool = False
    cash_reserve_amount: float = 0
    available_cash: Optional[float] = None
    confirmed_cash: Optional[float] = None
    funding_accounts: List[Dict[str, Any]] = Field(default_factory=list)
    total_recommended_add: float = 0
    data_quality: Literal["ok", "partial"]
    limitations: List[str] = Field(default_factory=list)
    known_current_amount: float
    unassigned_current_amount: float
    unassigned_positions: List[PortfolioAllocationUnassignedPosition] = Field(default_factory=list)
    targets: List[PortfolioAllocationTargetStatus] = Field(default_factory=list)
    disclosures: List[str] = Field(default_factory=list)
