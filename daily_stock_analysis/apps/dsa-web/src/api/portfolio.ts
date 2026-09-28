import apiClient from './index';
import { toCamelCase } from './utils';
import type { TaskAccepted } from '../types/analysis';
import type {
  AllocationPlan,
  AllocationPlanWrite,
  AllocationStatus,
  OpeningBalanceWrite, OpeningPreview, FundingWrite, AccountState,
  PortfolioAccountItem,
  PortfolioAccountCreateRequest,
  PortfolioAccountListResponse,
  PortfolioCashLedgerCreateRequest,
  PortfolioCashLedgerListResponse,
  PortfolioCorporateActionCreateRequest,
  PortfolioCorporateActionListResponse,
  PortfolioCostMethod,
  PortfolioDeleteResponse,
  PortfolioEventCreatedResponse,
  PortfolioFxRefreshResponse,
  PortfolioImportBrokerListResponse,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionAnalysisRequest,
  PortfolioRiskResponse,
  PortfolioSnapshotResponse,
  PortfolioTradeCreateRequest,
  PortfolioTradeListResponse,
} from '../types/portfolio';

type SnapshotQuery = {
  accountId?: number;
  asOf?: string;
  costMethod?: PortfolioCostMethod;
  includeRealtime?: boolean;
};

type FxRefreshQuery = {
  accountId?: number;
  asOf?: string;
};

type EventQuery = {
  accountId?: number;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
};

type TradeListQuery = EventQuery & {
  symbol?: string;
  side?: 'buy' | 'sell';
};

type CashListQuery = EventQuery & {
  direction?: 'in' | 'out';
};

type CorporateListQuery = EventQuery & {
  symbol?: string;
  actionType?: 'cash_dividend' | 'split_adjustment';
};

function buildSnapshotParams(query: SnapshotQuery): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (query.accountId != null) {
    params.account_id = query.accountId;
  }
  if (query.asOf) {
    params.as_of = query.asOf;
  }
  if (query.costMethod) {
    params.cost_method = query.costMethod;
  }
  if (query.includeRealtime !== undefined) {
    params.include_realtime = query.includeRealtime ? 'true' : 'false';
  }
  return params;
}

function buildFxRefreshParams(query: FxRefreshQuery): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (query.accountId != null) {
    params.account_id = query.accountId;
  }
  if (query.asOf) {
    params.as_of = query.asOf;
  }
  return params;
}

function buildEventParams(query: EventQuery): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (query.accountId != null) {
    params.account_id = query.accountId;
  }
  if (query.dateFrom) {
    params.date_from = query.dateFrom;
  }
  if (query.dateTo) {
    params.date_to = query.dateTo;
  }
  if (query.page != null) {
    params.page = query.page;
  }
  if (query.pageSize != null) {
    params.page_size = query.pageSize;
  }
  return params;
}

export const portfolioApi = {
  async getAccountState(accountId: number): Promise<AccountState> {
    return toCamelCase((await apiClient.get(`/api/v1/portfolio/accounts/${accountId}/state`)).data);
  },

  async previewOpeningBalance(accountId: number, value: OpeningBalanceWrite): Promise<OpeningPreview> {
    const body = openingPayload(value);
    return toCamelCase((await apiClient.post(`/api/v1/portfolio/accounts/${accountId}/opening-balance/preview`, body)).data);
  },

  async commitOpeningBalance(accountId: number, value: OpeningBalanceWrite, previewToken: string): Promise<void> {
    await apiClient.post(`/api/v1/portfolio/accounts/${accountId}/opening-balance`, {
      ...openingPayload(value), preview_token: previewToken, confirmed: true,
    });
  },

  async saveFunding(accountId: number, value: FundingWrite): Promise<void> {
    await apiClient.post(`/api/v1/portfolio/accounts/${accountId}/funding`, {
      as_of: value.asOf, settled_cash: value.settledCash, available_cash: value.availableCash,
      planned_deposit: value.plannedDeposit, planned_deposit_date: value.plannedDepositDate,
    });
  },

  async getAllocationPlans(): Promise<{ plans: Omit<AllocationPlan, 'targets'>[] }> {
    const response = await apiClient.get('/api/v1/portfolio/allocation-plans');
    return toCamelCase(response.data);
  },

  async getAllocationPlan(id: number): Promise<AllocationPlan> {
    const response = await apiClient.get(`/api/v1/portfolio/allocation-plans/${id}`);
    return toCamelCase(response.data);
  },

  async saveAllocationPlan(plan: AllocationPlanWrite, id?: number): Promise<AllocationPlan> {
    const payload = {
      name: plan.name, owner_id: plan.ownerId, base_currency: plan.baseCurrency,
      target_total_value: plan.targetTotalValue, account_id: plan.accountId,
      ledger_complete: plan.ledgerComplete, cash_reserve_amount: plan.cashReserveAmount,
      include_in_reports: plan.includeInReports,
      targets: plan.targets.map((target, index) => ({
        key: target.key, name: target.name, source: target.source, policy: target.policy,
        market: target.market, symbols: target.symbols, target_pct: target.targetPct,
        min_pct: target.minPct, max_pct: target.maxPct, batch_amount: target.batchAmount,
        current_amount: target.currentAmount, sort_order: index, note: target.note,
      })),
    };
    const response = id
      ? await apiClient.put(`/api/v1/portfolio/allocation-plans/${id}`, payload)
      : await apiClient.post('/api/v1/portfolio/allocation-plans', payload);
    return toCamelCase(response.data);
  },

  async getAllocationStatus(id: number, query: SnapshotQuery = {}): Promise<AllocationStatus> {
    const response = await apiClient.get(`/api/v1/portfolio/allocation-plans/${id}/status`, {
      params: buildSnapshotParams(query),
    });
    return toCamelCase(response.data);
  },

  async getAccounts(includeInactive = false): Promise<PortfolioAccountListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/accounts', {
      params: { include_inactive: includeInactive },
    });
    return toCamelCase<PortfolioAccountListResponse>(response.data);
  },

  async createAccount(payload: PortfolioAccountCreateRequest): Promise<PortfolioAccountItem> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/accounts', {
      name: payload.name,
      broker: payload.broker,
      market: payload.market,
      base_currency: payload.baseCurrency,
      owner_id: payload.ownerId,
    });
    return toCamelCase<PortfolioAccountItem>(response.data);
  },

  async deleteAccount(accountId: number): Promise<PortfolioDeleteResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(`/api/v1/portfolio/accounts/${accountId}`);
    return toCamelCase<PortfolioDeleteResponse>(response.data);
  },

  async getSnapshot(query: SnapshotQuery = {}): Promise<PortfolioSnapshotResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/snapshot', {
      params: buildSnapshotParams(query),
    });
    return toCamelCase<PortfolioSnapshotResponse>(response.data);
  },

  async analyzePosition(symbol: string, payload: PortfolioPositionAnalysisRequest = {}): Promise<TaskAccepted> {
    const response = await apiClient.post<Record<string, unknown>>(
      `/api/v1/portfolio/positions/${encodeURIComponent(symbol)}/analysis`,
      {
        account_id: payload.accountId,
        analysis_phase: payload.analysisPhase ?? 'auto',
        force: payload.force ?? false,
      },
    );
    return toCamelCase<TaskAccepted>(response.data);
  },

  async getRisk(query: SnapshotQuery = {}): Promise<PortfolioRiskResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/risk', {
      params: buildSnapshotParams(query),
    });
    return toCamelCase<PortfolioRiskResponse>(response.data);
  },

  async refreshFx(query: FxRefreshQuery = {}): Promise<PortfolioFxRefreshResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/fx/refresh', undefined, {
      params: buildFxRefreshParams(query),
    });
    return toCamelCase<PortfolioFxRefreshResponse>(response.data);
  },

  async createTrade(payload: PortfolioTradeCreateRequest): Promise<PortfolioEventCreatedResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/trades', {
      account_id: payload.accountId,
      symbol: payload.symbol,
      trade_date: payload.tradeDate,
      side: payload.side,
      quantity: payload.quantity,
      price: payload.price,
      fee: payload.fee ?? 0,
      tax: payload.tax ?? 0,
      market: payload.market,
      currency: payload.currency,
      trade_uid: payload.tradeUid,
      note: payload.note,
    });
    return toCamelCase<PortfolioEventCreatedResponse>(response.data);
  },

  async deleteTrade(tradeId: number): Promise<PortfolioDeleteResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(`/api/v1/portfolio/trades/${tradeId}`);
    return toCamelCase<PortfolioDeleteResponse>(response.data);
  },

  async createCashLedger(payload: PortfolioCashLedgerCreateRequest): Promise<PortfolioEventCreatedResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/cash-ledger', {
      account_id: payload.accountId,
      event_date: payload.eventDate,
      direction: payload.direction,
      amount: payload.amount,
      currency: payload.currency,
      note: payload.note,
    });
    return toCamelCase<PortfolioEventCreatedResponse>(response.data);
  },

  async deleteCashLedger(entryId: number): Promise<PortfolioDeleteResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(`/api/v1/portfolio/cash-ledger/${entryId}`);
    return toCamelCase<PortfolioDeleteResponse>(response.data);
  },

  async createCorporateAction(payload: PortfolioCorporateActionCreateRequest): Promise<PortfolioEventCreatedResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/corporate-actions', {
      account_id: payload.accountId,
      symbol: payload.symbol,
      effective_date: payload.effectiveDate,
      action_type: payload.actionType,
      market: payload.market,
      currency: payload.currency,
      cash_dividend_per_share: payload.cashDividendPerShare,
      split_ratio: payload.splitRatio,
      note: payload.note,
    });
    return toCamelCase<PortfolioEventCreatedResponse>(response.data);
  },

  async deleteCorporateAction(actionId: number): Promise<PortfolioDeleteResponse> {
    const response = await apiClient.delete<Record<string, unknown>>(`/api/v1/portfolio/corporate-actions/${actionId}`);
    return toCamelCase<PortfolioDeleteResponse>(response.data);
  },

  async listTrades(query: TradeListQuery = {}): Promise<PortfolioTradeListResponse> {
    const params = buildEventParams(query);
    if (query.symbol) {
      params.symbol = query.symbol;
    }
    if (query.side) {
      params.side = query.side;
    }
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/trades', { params });
    return toCamelCase<PortfolioTradeListResponse>(response.data);
  },

  async listCashLedger(query: CashListQuery = {}): Promise<PortfolioCashLedgerListResponse> {
    const params = buildEventParams(query);
    if (query.direction) {
      params.direction = query.direction;
    }
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/cash-ledger', { params });
    return toCamelCase<PortfolioCashLedgerListResponse>(response.data);
  },

  async listCorporateActions(query: CorporateListQuery = {}): Promise<PortfolioCorporateActionListResponse> {
    const params = buildEventParams(query);
    if (query.symbol) {
      params.symbol = query.symbol;
    }
    if (query.actionType) {
      params.action_type = query.actionType;
    }
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/corporate-actions', { params });
    return toCamelCase<PortfolioCorporateActionListResponse>(response.data);
  },

  async listImportBrokers(): Promise<PortfolioImportBrokerListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/imports/csv/brokers');
    return toCamelCase<PortfolioImportBrokerListResponse>(response.data);
  },

  async parseCsvImport(broker: string, file: File): Promise<PortfolioImportParseResponse> {
    const formData = new FormData();
    formData.append('broker', broker);
    formData.append('file', file);
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/imports/csv/parse', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return toCamelCase<PortfolioImportParseResponse>(response.data);
  },

  async commitCsvImport(
    accountId: number,
    broker: string,
    file: File,
    dryRun = false,
  ): Promise<PortfolioImportCommitResponse> {
    const formData = new FormData();
    formData.append('account_id', String(accountId));
    formData.append('broker', broker);
    formData.append('dry_run', dryRun ? 'true' : 'false');
    formData.append('file', file);
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/imports/csv/commit', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return toCamelCase<PortfolioImportCommitResponse>(response.data);
  },
};

function openingPayload(value: OpeningBalanceWrite) {
  return { as_of: value.asOf, cash_balance: value.cashBalance,
    reported_market_value: value.reportedMarketValue, reported_equity: value.reportedEquity,
    positions: value.positions.map((p) => ({ symbol: p.symbol, quantity: p.quantity,
      avg_cost: p.avgCost, reported_market_value: p.reportedMarketValue })) };
}
