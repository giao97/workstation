import apiClient from './index';

export type CompositionCoverage = { status: string; age_days: number; disclosed_pct: number; equity_pct: number;
  nested_fund_pct: number; cash_pct: number; other_pct: number; undisclosed_pct: number };
export type CompositionPreview = { content_hash: string; coverage: CompositionCoverage; can_write_portfolio: false };
export type ExposureReport = {
  generated_at: string; account_id: number | null; freshness_policy_days: number; library_count: number;
  holding_context: { status: string; profile_date?: string }; portfolio_exposure_pct: null;
  holdings: Array<{ market: string; symbol: string }>;
  unclassified_holdings: Array<{ market: string; symbol: string }>;
  funds: Array<{ id: number; fund_symbol: string; holdings_as_of: string; source_name: string; source_url: string;
    source_published_at: string | null; recorded_at: string; content_hash: string; row_count: number; coverage: CompositionCoverage }>;
  pairs: Array<{ left: string; right: string; status: string; observed_overlap_pct: number | null; shared_count: number | null;
    left_snapshot_id: number; right_snapshot_id: number;
    shared: Array<{ market: string; symbol: string; left_weight_pct: number; right_weight_pct: number; overlap_pct: number }> }>;
  held_constituent_matches: Array<{ fund: string; symbol: string; market: string; fund_weight_pct: number; snapshot_id: number }>;
};

export const etfExposureApi = {
  async report(accountId?: number) {
    return (await apiClient.get<ExposureReport>('/api/v1/portfolio/etf-exposure', { params: { account_id: accountId } })).data;
  },
  async preview(snapshot: Record<string, unknown>) {
    return (await apiClient.post<CompositionPreview>('/api/v1/portfolio/etf-compositions/preview', snapshot)).data;
  },
  async save(snapshot: Record<string, unknown>) {
    return (await apiClient.post('/api/v1/portfolio/etf-compositions', { snapshot, source_reviewed: true })).data;
  },
};
