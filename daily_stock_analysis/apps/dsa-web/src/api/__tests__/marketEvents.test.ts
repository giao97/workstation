import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { marketEventsApi, NewsJobFailed, type BriefInput } from '../marketEvents';
const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../index', () => ({ default: client }));
const input: BriefInput = { request_key: 'test_news_key_0001', market: 'us', language: 'zh',
  search_news: false, refresh_sources: false, analyze: true, manual_items: [] };
describe('news background jobs', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });
  it('submits once, polls progress, then reads the immutable archive', async () => {
    client.post.mockResolvedValue({ data: { status: 'pending', stage: 'pending', brief_id: null } });
    client.get.mockResolvedValueOnce({ data: { status: 'processing', stage: 'interpreting', brief_id: null } })
      .mockResolvedValueOnce({ data: { status: 'completed', stage: 'archived', brief_id: 42 } })
      .mockResolvedValueOnce({ data: { id: 42 } });
    const progress = vi.fn();
    const work = marketEventsApi.generate(input, progress);
    await vi.advanceTimersByTimeAsync(3000);
    expect(await work).toEqual({ id: 42 });
    expect(client.post).toHaveBeenCalledTimes(1);
    expect(progress.mock.calls.map(([j]) => j.stage)).toEqual(['pending', 'interpreting', 'archived']);
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/market-events/42', { signal: undefined });
  });
  it('recovery never submits or retries a model call', async () => {
    client.get.mockResolvedValue({ data: { status: 'failed', stage: 'failed', brief_id: null } });
    await expect(marketEventsApi.waitForJob(input.request_key)).rejects.toBeInstanceOf(NewsJobFailed);
    expect(client.post).not.toHaveBeenCalled();
  });
  it('unknown status stops polling without claiming cancellation or completion', async () => {
    client.get.mockResolvedValue({ data: { status: 'unknown', stage: 'unknown', brief_id: null } });
    await expect(marketEventsApi.waitForJob(input.request_key)).rejects.toThrow('market_event_job_unknown');
    expect(client.get).toHaveBeenCalledTimes(1);
    expect(client.post).not.toHaveBeenCalled();
  });
  it('abort stops client polling, without sending a cancellation', async () => {
    client.get.mockResolvedValue({ data: { status: 'processing', stage: 'interpreting', brief_id: null } });
    const control = new AbortController();
    const work = marketEventsApi.waitForJob(input.request_key, undefined, control.signal);
    const rejected = expect(work).rejects.toThrow('aborted');
    await vi.advanceTimersByTimeAsync(0);
    control.abort(); await rejected;
    await vi.advanceTimersByTimeAsync(3000);
    expect(client.get).toHaveBeenCalledTimes(1);
    expect(client.post).not.toHaveBeenCalled();
  });
  it('retry sends only parent id and idempotency key, not refreshed evidence', async () => {
    client.post.mockResolvedValue({ data: { status: 'completed', stage: 'archived', brief_id: 43 } });
    client.get.mockResolvedValue({ data: { id: 43, parent_brief_id: 42 } });
    expect(await marketEventsApi.retryAnalysis(42, input.request_key)).toEqual({ id: 43, parent_brief_id: 42 });
    expect(client.post).toHaveBeenCalledWith('/api/v1/market-events/42/retry-analysis',
      { request_key: input.request_key }, { signal: undefined });
  });
});
