import { beforeEach, describe, expect, it, vi } from 'vitest';
import { paperObservationsApi, type PaperAssumptions } from '../paperObservations';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../index', () => ({ default: api }));
const assumptions: PaperAssumptions = { quantity: 20, baseline_shares: 105, protected_shares: 85, cash_usd: 1000,
  buy_fee_usd: 1.04, sell_fee_usd: 1.07, slippage_bps: 10, fee_note: 'Synthetic' };
describe('paperObservationsApi', () => {
  beforeEach(() => { vi.clearAllMocks(); api.post.mockResolvedValue({ data: {} }); });
  it('keeps the original daily request compatible', async () => {
    await paperObservationsApi.capture(1, 'key', assumptions);
    expect(api.post).toHaveBeenCalledWith('/api/v1/paper-observations', { signal_id: 1, request_key: 'key', assumptions });
  });
  it('passes immutable minute rules without renaming opaque source fields', async () => {
    const rules = { entry_price: 30, exit_price: 29, invalidation_price: 33, expires_at: '2026-09-29T20:00:00Z' };
    const stored = { snapshot: { minute_rules: rules, paper_policy_version: 'paper-minute-v1' } };
    api.post.mockResolvedValue({ data: stored });
    expect(await paperObservationsApi.capture(1, 'key', assumptions, rules)).toEqual(stored);
    expect(api.post).toHaveBeenCalledWith('/api/v1/paper-observations', { signal_id: 1, request_key: 'key', assumptions, minute_rules: rules });
  });
});
