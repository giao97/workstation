import { beforeEach, describe, expect, it, vi } from 'vitest';
import { portfolioApi } from '../portfolio';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../index', () => ({ default: api }));
describe('allocation review API', () => {
  beforeEach(() => { vi.resetAllMocks(); });
  it('passes the scope and pagination cursor, preserving enum values', async () => {
    api.get.mockResolvedValue({ data: { plan_version: 2, latest: [{ horizon: 'long_term', review_due_at: 'time' }], items: [], next_before_id: 9 } });
    const response = await portfolioApi.getAllocationReviews(1, 'core', 10);
    expect(api.get).toHaveBeenCalledWith('/api/v1/portfolio/allocation-plans/1/reviews', { params: { target_key: 'core', before_id: 10 } });
    expect(response.latest[0]).toEqual({ horizon: 'long_term', reviewDueAt: 'time' });
    expect(response.nextBeforeId).toBe(9);
  });
  it('submits only the manual review contract', async () => {
    api.post.mockResolvedValue({ data: { id: 3, expected_previous_id: 2 } });
    await portfolioApi.saveAllocationReview(1, { requestKey: 'retry', expectedPlanVersion: 4, expectedPreviousId: 2,
      targetKey: 'core', horizon: 'tactical', decision: 'wait', reason: 'reason', evidence: 'unknown', nextCondition: 'condition', reviewDueAt: 'time' });
    expect(api.post).toHaveBeenCalledWith('/api/v1/portfolio/allocation-plans/1/reviews', {
      request_key: 'retry', expected_plan_version: 4, expected_previous_id: 2, target_key: 'core', horizon: 'tactical',
      decision: 'wait', reason: 'reason', evidence: 'unknown', next_condition: 'condition', review_due_at: 'time' });
  });
});
