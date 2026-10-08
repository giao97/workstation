import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EtfExposurePanel } from './EtfExposurePanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { ExposureReport } from '../../api/etfExposure';
import type { PortfolioAccountItem } from '../../types/portfolio';
const api = vi.hoisted(() => ({ report: vi.fn(), preview: vi.fn(), save: vi.fn() }));
vi.mock('../../api/etfExposure', () => ({ etfExposureApi: api }));
const coverage = { status: 'eligible', age_days: 1, disclosed_pct: 10, equity_pct: 10,
  nested_fund_pct: 0, cash_pct: 0, other_pct: 0, undisclosed_pct: 90 };
const report = (patch: Partial<ExposureReport> = {}): ExposureReport => ({ generated_at: '2026-09-29T11:00:00Z',
  account_id: null, freshness_policy_days: 7, library_count: 0, holding_context: { status: 'profile_reference', profile_date: '2026-09-29' },
  portfolio_exposure_pct: null, holdings: [{ market: 'us', symbol: 'VOO' }, { market: 'us', symbol: 'TSLA' }],
  unclassified_holdings: [{ market: 'us', symbol: 'VOO' }, { market: 'us', symbol: 'TSLA' }], funds: [], pairs: [],
  held_constituent_matches: [], ...patch });
const accounts = [{ id: 1, name: 'Synthetic account', isActive: true }] as PortfolioAccountItem[];
const mount = () => render(<UiLanguageProvider><EtfExposurePanel accounts={accounts} /></UiLanguageProvider>);

describe('ETF exposure panel', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.report.mockResolvedValue(report()); api.save.mockResolvedValue({ id: 1 });
    api.preview.mockResolvedValue({ coverage, content_hash: 'hash', can_write_portfolio: false });
  });
  it('starts with read-only gaps, never sample holdings or model weights', async () => {
    mount(); await screen.findByText(/暂无与持仓匹配的成分快照/);
    expect(screen.getByText(/组合金额\/行业占比：尚未计算/)).toBeInTheDocument();
    expect(screen.getByText(/VOO \/ TSLA/)).toBeInTheDocument();
    expect(api.save).not.toHaveBeenCalled(); expect(api.preview).not.toHaveBeenCalled();
  });
  it('requires preview and explicit review before saving research evidence', async () => {
    mount(); await screen.findByText(/暂无与持仓匹配/);
    fireEvent.change(screen.getByLabelText('成分 JSON'), { target: { value: '{"fund_symbol":"VOO"}' } });
    fireEvent.click(screen.getByText('校验预览（不保存）'));
    await screen.findByText('确认保存成分快照');
    expect(screen.getByText('确认保存成分快照')).toBeDisabled();
    expect(api.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(/我已核对来源/));
    fireEvent.click(screen.getByText('确认保存成分快照'));
    await screen.findByText(/成分快照已保存；未修改持仓、现金或交易/);
    expect(api.save).toHaveBeenCalledWith({ fund_symbol: 'VOO' });
    await waitFor(() => expect(api.report).toHaveBeenCalledTimes(2));
  });
  it('invalidates preview and confirmation when input changes', async () => {
    mount(); await screen.findByText(/暂无与持仓匹配/);
    fireEvent.change(screen.getByLabelText('成分 JSON'), { target: { value: '{}' } });
    fireEvent.click(screen.getByText('校验预览（不保存）')); await screen.findByText('确认保存成分快照');
    fireEvent.click(screen.getByLabelText(/我已核对来源/));
    fireEvent.change(screen.getByLabelText('成分 JSON'), { target: { value: '{"new":true}' } });
    expect(screen.queryByText('确认保存成分快照')).not.toBeInTheDocument();
    expect(api.save).not.toHaveBeenCalled();
  });
  it('ignores late results after switching account scope', async () => {
    let finish!: (r: ExposureReport) => void;
    api.report.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce(report({ holdings: [], unclassified_holdings: [], holding_context: { status: 'no_recorded_holdings' } }));
    mount(); fireEvent.change(screen.getByLabelText('穿透持仓范围'), { target: { value: '1' } });
    await screen.findByText(/未读取到已记录持仓，不代表实际空仓/);
    await act(async () => finish(report()));
    expect(screen.queryByText(/VOO \/ TSLA/)).not.toBeInTheDocument();
    expect(api.report).toHaveBeenLastCalledWith(1);
  });
  it('shows zero separately from blocked comparisons, never as portfolio weight', async () => {
    api.report.mockResolvedValue(report({ pairs: [
      { left: 'AAA', right: 'BBB', status: 'observed_only', observed_overlap_pct: 0, shared_count: 0, shared: [], left_snapshot_id: 1, right_snapshot_id: 2 },
      { left: 'AAA', right: 'CCC', status: 'date_mismatch', observed_overlap_pct: null, shared_count: null, shared: [], left_snapshot_id: 1, right_snapshot_id: 3 },
    ] }));
    mount(); await screen.findByText(/已披露交集 0.00%/);
    expect(screen.getByText(/成分日期不同，不混算/)).toBeInTheDocument();
    expect(screen.getByText(/0% 仅表示已披露部分未匹配/)).toBeInTheDocument();
  });
  it('provides English empty-state labels', async () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); mount();
    await screen.findByText(/No compositions match these holdings/);
    expect(screen.getByText('ETF look-through · overlap review')).toBeInTheDocument();
  });
});
