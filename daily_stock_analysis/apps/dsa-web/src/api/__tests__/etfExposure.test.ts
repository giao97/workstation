import { beforeEach, describe, expect, it, vi } from 'vitest';
import { etfExposureApi } from '../etfExposure';
const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../index', () => ({ default: client }));
describe('ETF evidence API', () => {
  beforeEach(() => { vi.resetAllMocks(); client.get.mockResolvedValue({ data: {} }); client.post.mockResolvedValue({ data: {} }); });
  it('reads the selected scope without valuation or generation flags', async () => {
    await etfExposureApi.report(2);
    expect(client.get).toHaveBeenCalledWith('/api/v1/portfolio/etf-exposure', { params: { account_id: 2 } });
    expect(client.post).not.toHaveBeenCalled();
  });
  it('keeps preview distinct from explicit source attestation', async () => {
    const snapshot = { fund_symbol: 'AAA' };
    await etfExposureApi.preview(snapshot);
    expect(client.post).toHaveBeenLastCalledWith('/api/v1/portfolio/etf-compositions/preview', snapshot);
    await etfExposureApi.save(snapshot);
    expect(client.post).toHaveBeenLastCalledWith('/api/v1/portfolio/etf-compositions', { snapshot, source_reviewed: true });
  });
});
