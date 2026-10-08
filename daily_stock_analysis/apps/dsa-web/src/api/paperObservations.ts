import apiClient from './index';

// Keep evidence and archived source payload in their original snake_case format.
export type PaperAssumptions = {
  quantity: number; baseline_shares: number; protected_shares: number; cash_usd: number;
  buy_fee_usd: number; sell_fee_usd: number; slippage_bps: number; fee_note: string;
};
export type MinuteRules = { entry_price: number; exit_price: number; invalidation_price: number; expires_at: string };
export type PaperExperiment = {
  id: number; signal_id: number; captured_at: string; snapshot_hash: string;
  snapshot: { stock_code: string; action: string; status: string; reason?: string; paper_policy_version?: string;
    minute_rules?: MinuteRules; minute_session?: { start: string; end: string; warmup: string } };
  assumptions: PaperAssumptions;
};
export type PaperOutcome = {
  horizon: number; status: string; reason?: string | null; relative_hold_pnl?: number | null;
  closed_net_pnl?: number | null; economic_cost_improvement_per_share?: number | null;
  opportunity_loss?: number | null; ending_shares?: number; ending_cash?: number;
  observed_at?: string; fetched_at?: string; source?: string; source_url?: string;
  evidence_hash?: string; entry_date?: string; end_date?: string;
  fills?: Array<{ side: string; timestamp?: string; confirmation_bar?: string; price: number; quantity: number; fee: number }>;
  events?: Array<{ timestamp: string; kind: string; reason?: string; side?: string }>;
};
export type PaperEvaluation = { experiment: PaperExperiment; observed_at: string; engine_version: string; items: PaperOutcome[] };
export const paperObservationsApi = {
  async list(signalId: number) {
    return (await apiClient.get<{ items: PaperExperiment[] }>('/api/v1/paper-observations', { params: { signal_id: signalId } })).data;
  },
  async capture(signalId: number, requestKey: string, assumptions: PaperAssumptions, minuteRules?: MinuteRules) {
    return (await apiClient.post<PaperExperiment>('/api/v1/paper-observations', { signal_id: signalId, request_key: requestKey, assumptions,
      ...(minuteRules ? { minute_rules: minuteRules } : {}) })).data;
  },
  async evaluate(id: number) {
    return (await apiClient.post<PaperEvaluation>(`/api/v1/paper-observations/${id}/evaluate`)).data;
  },
};
