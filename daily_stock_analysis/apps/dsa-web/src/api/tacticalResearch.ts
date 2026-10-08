import apiClient from './index';

export type TacticalLot = { symbol: string; investment_usd: number; planned_loss_pct: number;
  round_trip_cost_usd: number | null; thesis: string; invalidation: string };
export type TacticalInput = { available_cash_usd: number; cash_as_of: string;
  cash_net_of_other_budgets: boolean; loss_tolerance_pct: number; lots: TacticalLot[] };
export type TacticalPreview = { state: string; executable: false; evaluated_at: string;
  cash_required_usd: number | null; remaining_cash_usd: number | null;
  planned_loss_usd: number | null; tolerance_usd: number; reasons: string[] };
export async function previewTactical(input: TacticalInput) {
  return (await apiClient.post<TacticalPreview>('/api/v1/portfolio/tactical-research/preview', input)).data;
}
