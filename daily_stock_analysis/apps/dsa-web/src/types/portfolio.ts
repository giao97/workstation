import type { DecisionSignalItem } from './decisionSignals';

export type PortfolioCostMethod = 'fifo' | 'avg';
export type PortfolioSide = 'buy' | 'sell';
export type PortfolioCashDirection = 'in' | 'out';
export type PortfolioCorporateActionType = 'cash_dividend' | 'split_adjustment';

export interface PerformanceReviewRequest {
  startDate: string;
  endDate: string;
  symbols: string[];
  ledgerConfirmed: boolean;
  includeRealtime: boolean;
}

export interface TradingContribution {
  symbol: string;
  market: string;
  currency: string;
  status: 'restored' | 'under_baseline' | 'over_baseline' | 'no_activity' | 'unsupported';
  baselineQuantity: number;
  endingQuantity: number;
  baselineKind: 'unchanged_shares' | 'unchanged_cash';
  shareGap: number | null;
  unrecoveredQuantity: number | null;
  extraQuantity: number | null;
  buyNotional: number;
  sellNotional: number;
  grossCashFlow: number;
  recordedCosts: number;
  costsConfirmed: boolean;
  netCashFlow: number | null;
  closedNetPnl: number | null;
  relativeHoldPnl: number | null;
  markDifference: number | null;
  economicCostImprovementPerShare: number | null;
  comparisonKind: 'unavailable' | 'marked_estimate' | 'cash_difference';
  unverifiedFeeTradeIds: number[];
  tradeCount: number;
  limitations: string[];
  trades: PortfolioTradeListItem[];
  corporateActions: Array<Record<string, unknown>>;
  valuation: { price: number | null; source: string | null; provider: string | null;
    timestamp: string | null; fetchedAt: string | null; usable: boolean; reason: string } | null;
}

export interface PerformanceReview {
  accountId: number;
  startDate: string;
  endDate: string;
  timezone: string;
  requestedSymbols: string[];
  ledgerConfirmed: boolean;
  methodologyVersion: string;
  ledgerFingerprint: string;
  evidenceHash: string;
  generatedAt: string;
  items: TradingContribution[];
  totalsByCurrency: Array<{ currency: string; itemCount: number; comparableCount: number;
    closedVerifiedCount: number; verifiedClosedNetPnl: number | null; relativeHoldPnl: number | null;
    containsMarkedEstimate: boolean }>;
  disclosures: string[];
}

export interface AllocationTarget {
  key: string;
  name: string;
  source: 'position' | 'cash' | 'manual';
  policy: 'buy_only' | 'rebalance' | 'hold_only' | 'exit_only';
  market?: PortfolioAccountItem['market'] | null;
  symbols: string[];
  targetPct: number;
  minPct?: number | null;
  maxPct?: number | null;
  batchAmount?: number | null;
  currentAmount?: number | null;
  sortOrder: number;
  note?: string | null;
}

export interface AllocationPlanWrite {
  name: string;
  ownerId?: string | null;
  baseCurrency: string;
  targetTotalValue: number;
  accountId: number | null;
  ledgerComplete: boolean;
  cashReserveAmount: number;
  includeInReports: boolean;
  targets: AllocationTarget[];
}

export interface AllocationPlan extends AllocationPlanWrite {
  id: number;
  version: number;
  isActive: boolean;
}

export interface AllocationTargetStatus extends Omit<AllocationTarget, 'currentAmount'> {
  coreEntries?: CoreEntryAssessment[];
  currentAmount: number | null;
  currentPct: number | null;
  targetAmount: number;
  gapAmount: number | null;
  allocationCap: number;
  fundedAmount?: number | null;
  isEstimate?: boolean;
  referenceNotes?: string[];
  recommendedAmount: number;
  action: 'add' | 'reduce' | 'hold' | 'review';
  reason: string;
  dataComplete: boolean;
  limitations: string[];
}

export interface CoreEntryAssessment {
  symbol: string;
  method: string;
  state: 'candidate' | 'wait' | 'risk_review' | 'data_required';
  asOf: string | null;
  evaluatedAt: string;
  sources: string[];
  metrics: Record<string, number>;
  reasons: string[];
  checks: string[];
  limitations: string[];
  executable: false;
  allocationReady: boolean;
  allocationAction: string;
}

export interface AllocationStatus {
  planId: number;
  planName: string;
  planVersion: number;
  baseCurrency: string;
  targetTotalValue: number;
  accountId: number | null;
  asOf: string;
  ledgerComplete: boolean;
  cashReserveAmount: number;
  availableCash: number | null;
  confirmedCash?: number | null;
  fundingAccounts?: Array<{ accountId: number; currency: string; cashConfirmed: boolean;
    confirmedCashCap: number | null; plannedDeposit: number | null; plannedDepositDate: string | null }>;
  totalRecommendedAdd: number;
  dataQuality: 'ok' | 'partial';
  limitations: string[];
  targets: AllocationTargetStatus[];
  unassignedPositions: Array<{ symbol: string; currentAmount: number; priceAvailable: boolean }>;
}

export interface AllocationReviewWrite {
  requestKey: string; expectedPlanVersion: number; expectedPreviousId: number | null;
  targetKey: string; horizon: 'long_term' | 'tactical';
  decision: 'maintain_plan' | 'wait' | 'data_required' | 'pause';
  reason: string; evidence: string; nextCondition: string; reviewDueAt: string;
}

export interface AllocationReview extends AllocationReviewWrite {
  id: number; planId: number; revision: number; createdAt: string;
  targetSnapshot: AllocationTarget; authority: 'manual_unverified';
  state: 'active' | 'due' | 'plan_changed' | 'plan_inactive';
}

export interface AllocationReviewList {
  planVersion: number; latest: AllocationReview[]; items: AllocationReview[]; nextBeforeId: number | null;
}

export interface PortfolioAccountItem {
  id: number;
  ownerId?: string | null;
  name: string;
  broker?: string | null;
  market: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  baseCurrency: string;
  isActive: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface ProfilePreview {
  profileDate: string; market: 'us'; currency: 'USD'; status: 'reference' | 'stale';
  sourceHash: string; canCommit: false; cashBalance: null; openingDate: null;
  positions: Array<{ symbol: string; quantity: number | null; quantityText: string; costText: string; costStatus: 'requires_confirmation' }>;
}

export interface OpeningPosition {
  symbol: string;
  quantity: number;
  avgCost: number;
  reportedMarketValue: number | null;
}

export interface OpeningBalanceWrite {
  asOf: string;
  positions: OpeningPosition[];
  cashBalance: number | null;
  reportedMarketValue: number | null;
  reportedEquity: number | null;
}

export interface OpeningPreview {
  accountId: number;
  opening: OpeningBalanceWrite & { currency: string; market: string };
  previewToken: string;
  canCommit: boolean;
  detailMarketValue: number | null;
  marketValueDifference: number | null;
  equityLessMarketValue: number | null;
  equityDifference: number | null;
  limitations: string[];
}

export interface FundingWrite {
  asOf: string;
  settledCash: number | null;
  availableCash: number | null;
  plannedDeposit: number | null;
  plannedDepositDate: string | null;
}

export interface AccountState {
  accountId: number;
  currency: string;
  opening: OpeningBalanceWrite | null;
  funding: (FundingWrite & { id: number; ledgerUnchanged: boolean }) | null;
  cashConfirmed: boolean;
  confirmedCashCap: number | null;
  disclosures: string[];
}

export interface PortfolioAccountListResponse {
  accounts: PortfolioAccountItem[];
}

export interface PortfolioAccountCreateRequest {
  name: string;
  broker?: string;
  market: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  baseCurrency: string;
  ownerId?: string;
}

export interface PortfolioPositionItem {
  symbol: string;
  market: string;
  currency: string;
  quantity: number;
  avgCost: number;
  totalCost: number;
  lastPrice: number;
  marketValueBase: number;
  unrealizedPnlBase: number;
  unrealizedPnlPct?: number | null;
  valuationCurrency: string;
  priceSource?: 'realtime_quote' | 'history_close' | 'missing' | string;
  priceProvider?: string | null;
  priceDate?: string | null;
  priceTimestamp?: string | null;
  priceFetchedAt?: string | null;
  priceStale?: boolean;
  priceAvailable?: boolean;
  dataQuality?: 'ok' | 'partial' | string;
  limitations?: string[];
}

export interface PortfolioPositionAnalysisRequest {
  accountId?: number;
  analysisPhase?: 'auto' | 'premarket' | 'intraday' | 'postmarket';
  force?: boolean;
}

export interface PortfolioAccountSnapshot {
  accountId: number;
  accountName: string;
  ownerId?: string | null;
  broker?: string | null;
  market: string;
  baseCurrency: string;
  asOf: string;
  costMethod: PortfolioCostMethod;
  totalCash: number;
  totalMarketValue: number;
  totalEquity: number;
  realizedPnl: number;
  unrealizedPnl: number;
  feeTotal: number;
  taxTotal: number;
  fxStale: boolean;
  dataQuality?: 'ok' | 'partial' | string;
  limitations?: string[];
  funding?: AccountState | null;
  positions: PortfolioPositionItem[];
}

export interface PortfolioSnapshotResponse {
  asOf: string;
  costMethod: PortfolioCostMethod;
  currency: string;
  accountCount: number;
  totalCash: number;
  totalMarketValue: number;
  totalEquity: number;
  realizedPnl: number;
  unrealizedPnl: number;
  feeTotal: number;
  taxTotal: number;
  fxStale: boolean;
  dataQuality?: 'ok' | 'partial' | string;
  limitations?: string[];
  accounts: PortfolioAccountSnapshot[];
}

export interface PortfolioConcentrationItem {
  symbol: string;
  marketValueBase: number;
  weightPct: number;
  isAlert: boolean;
}

export interface PortfolioSectorConcentrationItem {
  sector: string;
  marketValueBase: number;
  weightPct: number;
  symbolCount: number;
  isAlert: boolean;
}

export interface PortfolioDrawdownBlock {
  seriesPoints: number;
  maxDrawdownPct: number;
  currentDrawdownPct: number;
  alert: boolean;
  fxStale: boolean;
}

export interface PortfolioStopLossItem {
  accountId: number;
  symbol: string;
  avgCost: number;
  lastPrice: number;
  lossPct: number;
  nearThresholdPct: number;
  isTriggered: boolean;
}

export interface PortfolioDecisionSignalRiskItem {
  accountId?: number | null;
  symbol: string;
  market: string;
  signal: Partial<DecisionSignalItem>;
}

export interface PortfolioDecisionSignalRiskBlock {
  available: boolean;
  total: number;
  actions: {
    sell?: number;
    reduce?: number;
    alert?: number;
    [key: string]: number | undefined;
  };
  items: PortfolioDecisionSignalRiskItem[];
}

export interface PortfolioRiskResponse {
  asOf: string;
  accountId?: number | null;
  costMethod: PortfolioCostMethod;
  currency: string;
  thresholds: Record<string, number>;
  concentration: {
    totalMarketValue: number;
    topWeightPct: number;
    alert: boolean;
    topPositions: PortfolioConcentrationItem[];
  };
  sectorConcentration: {
    totalMarketValue: number;
    topWeightPct: number;
    alert: boolean;
    topSectors: PortfolioSectorConcentrationItem[];
    coverage: Record<string, number>;
    errors: string[];
  };
  drawdown: PortfolioDrawdownBlock;
  stopLoss: {
    nearAlert: boolean;
    triggeredCount: number;
    nearCount: number;
    items: PortfolioStopLossItem[];
  };
  decisionSignalRisk?: PortfolioDecisionSignalRiskBlock;
}

export interface PortfolioTradeCreateRequest {
  requestKey?: string;
  executedAt?: string;
  feeStatus?: 'unknown' | 'estimated' | 'confirmed';
  priceBasis?: 'execution';
  intentId?: number;
  accountId: number;
  symbol: string;
  tradeDate: string;
  side: PortfolioSide;
  quantity: number;
  price: number;
  fee?: number;
  tax?: number;
  market?: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  currency?: string;
  tradeUid?: string;
  note?: string;
}

export interface PortfolioCashLedgerCreateRequest {
  accountId: number;
  eventDate: string;
  direction: PortfolioCashDirection;
  amount: number;
  currency?: string;
  note?: string;
}

export interface PortfolioCorporateActionCreateRequest {
  accountId: number;
  symbol: string;
  effectiveDate: string;
  actionType: PortfolioCorporateActionType;
  market?: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  currency?: string;
  cashDividendPerShare?: number;
  splitRatio?: number;
  note?: string;
}

export interface PortfolioEventCreatedResponse {
  id: number;
}

export interface PortfolioDeleteResponse {
  deleted: number;
}

export interface PortfolioTradeListItem {
  executedAt?: string | null;
  feeStatus?: 'unknown' | 'estimated' | 'confirmed';
  revision?: number;
  intentId?: number | null;
  id: number;
  accountId: number;
  tradeUid?: string | null;
  symbol: string;
  market: string;
  currency: string;
  tradeDate: string;
  side: PortfolioSide;
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  note?: string | null;
  createdAt?: string | null;
}

export interface BudgetPeriod {
  id: number; name: string; accountId: number; currency: string; timezone: string;
  startDate: string; endDate: string; symbols: string[]; amount: number;
  ledgerComplete: boolean; activePeriod: boolean; confirmedSpent: number;
  reservedAmount: number; nativeReserved: number; remainingAmount: number | null;
  overBudgetAmount: number; unresolvedTradeIds: number[];
  trades: Array<{ tradeId: number; symbol: string; excluded: boolean; feeStatus: string;
    fxRate: number | null; amount: number | null }>;
  intents: Array<{ id: number; symbol: string; status: string; reportedStatus: string; revision: number;
    quantity: number; filledQuantity: number; remainingQuantity: number; reservedAmount: number; expiresAt: string }>;
}

export interface PortfolioTradeListResponse {
  items: PortfolioTradeListItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PortfolioCashLedgerListItem {
  id: number;
  accountId: number;
  eventDate: string;
  direction: PortfolioCashDirection;
  amount: number;
  currency: string;
  note?: string | null;
  createdAt?: string | null;
}

export interface PortfolioCashLedgerListResponse {
  items: PortfolioCashLedgerListItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PortfolioCorporateActionListItem {
  id: number;
  accountId: number;
  symbol: string;
  market: string;
  currency: string;
  effectiveDate: string;
  actionType: PortfolioCorporateActionType;
  cashDividendPerShare?: number | null;
  splitRatio?: number | null;
  note?: string | null;
  createdAt?: string | null;
}

export interface PortfolioCorporateActionListResponse {
  items: PortfolioCorporateActionListItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PortfolioImportTradeItem {
  tradeDate: string;
  symbol: string;
  side: PortfolioSide;
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  tradeUid?: string | null;
  dedupHash: string;
  currency?: string | null;
}

export interface PortfolioImportParseResponse {
  broker: string;
  recordCount: number;
  skippedCount: number;
  errorCount: number;
  records: PortfolioImportTradeItem[];
  errors: string[];
}

export interface PortfolioImportCommitResponse {
  accountId: number;
  recordCount: number;
  insertedCount: number;
  duplicateCount: number;
  failedCount: number;
  dryRun: boolean;
  errors: string[];
}

export interface PortfolioImportBrokerItem {
  broker: string;
  aliases: string[];
  displayName?: string;
}

export interface PortfolioImportBrokerListResponse {
  brokers: PortfolioImportBrokerItem[];
}

export interface PortfolioFxRefreshResponse {
  asOf: string;
  accountCount: number;
  refreshEnabled?: boolean;
  disabledReason?: string | null;
  pairCount: number;
  updatedCount: number;
  staleCount: number;
  errorCount: number;
}
