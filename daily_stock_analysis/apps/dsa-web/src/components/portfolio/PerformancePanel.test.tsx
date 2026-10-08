import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PerformancePanel } from './PerformancePanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { PerformanceReview, PortfolioAccountItem, TradingContribution } from '../../types/portfolio';

const api = vi.hoisted(() => ({ reviewPerformance: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const accounts = [1, 2].map((id) => ({ id, name: `Account ${id}`, market: 'us', baseCurrency: 'USD', isActive: true })) as PortfolioAccountItem[];
const item = (values: Partial<TradingContribution> = {}): TradingContribution => ({
  symbol: 'HAL', market: 'us', currency: 'USD', status: 'restored', baselineQuantity: 0, endingQuantity: 0,
  baselineKind: 'unchanged_cash', shareGap: 0, unrecoveredQuantity: 0, extraQuantity: 0,
  buyNotional: 327.50, sellNotional: 328.10, grossCashFlow: .6, recordedCosts: 0,
  costsConfirmed: false, netCashFlow: null, closedNetPnl: null, relativeHoldPnl: null,
  markDifference: null, economicCostImprovementPerShare: null, comparisonKind: 'unavailable',
  unverifiedFeeTradeIds: [1, 2], tradeCount: 2, limitations: ['performance_costs_unverified'],
  trades: [], corporateActions: [], valuation: null, ...values,
});
const report = (row = item()): PerformanceReview => ({
  accountId: 1, startDate: '2026-09-28', endDate: '2026-09-28', timezone: 'America/New_York',
  requestedSymbols: [], ledgerConfirmed: false, methodologyVersion: 'period-hold-v1',
  ledgerFingerprint: 'ledger-hash', evidenceHash: 'evidence-hash', generatedAt: '2026-09-29T00:00:00Z',
  items: [row], totalsByCurrency: [], disclosures: [],
});
const mount = (context?: object) => render(<UiLanguageProvider><PerformancePanel accounts={accounts} ledgerContext={context} /></UiLanguageProvider>);
const open = () => fireEvent.click(screen.getByRole('button', { name: '波段收益与持续持有对照' }));
const fill = () => {
  fireEvent.change(screen.getByLabelText('开始日期（含）'), { target: { value: '2026-09-28' } });
  fireEvent.change(screen.getByLabelText('结束日期（含）'), { target: { value: '2026-09-28' } });
};
const submit = () => fireEvent.submit(screen.getByRole('button', { name: '只读核算' }).closest('form')!);

describe('PerformancePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.reviewPerformance.mockResolvedValue(report());
  });
  it('never auto-fetches or implies trading when opened', () => {
    mount(); expect(api.reviewPerformance).not.toHaveBeenCalled(); open();
    expect(api.reviewPerformance).not.toHaveBeenCalled();
    expect(screen.getByText(/只读复盘，不下单、不修改成本/)).toBeInTheDocument();
  });
  it('sends explicit scope and defaults to unconfirmed, no live quote', async () => {
    mount(); open(); fill(); submit();
    await waitFor(() => expect(api.reviewPerformance).toHaveBeenCalledWith(1, {
      startDate: '2026-09-28', endDate: '2026-09-28', symbols: [], ledgerConfirmed: false, includeRealtime: false,
    }));
    expect(await screen.findByText('费用未全部核实，净收益未知')).toBeInTheDocument();
    expect(screen.getByText('0.60 USD')).toBeInTheDocument();
    expect(screen.getAllByText('待核实 / 不适用')).toHaveLength(3);
  });
  it('keeps negative HAL contribution and cash benchmark, without invented per-share improvement', async () => {
    api.reviewPerformance.mockResolvedValue(report(item({ closedNetPnl: -1.45, relativeHoldPnl: -1.45,
      recordedCosts: 2.05, costsConfirmed: true, limitations: [], unverifiedFeeTradeIds: [] })));
    mount(); open(); fill(); submit();
    expect(await screen.findByText(/保留现金基准，无原底仓降本/)).toBeInTheDocument();
    expect(screen.getAllByText('-1.45 USD')).toHaveLength(2);
    expect(screen.getByText('待核实 / 不适用')).toBeInTheDocument();
  });
  it('hides old numbers immediately when the scope changes', async () => {
    mount(); open(); fill(); submit(); await screen.findByText('0.60 USD');
    fireEvent.change(screen.getByLabelText('标的（留空按期间活动）'), { target: { value: 'EUV' } });
    expect(screen.queryByText('0.60 USD')).not.toBeInTheDocument();
  });
  it('invalidates a completed result after portfolio data refresh', async () => {
    const view = mount({ revision: 1 }); open(); fill(); submit(); await screen.findByText('0.60 USD');
    view.rerender(<UiLanguageProvider><PerformancePanel accounts={accounts} ledgerContext={{ revision: 2 }} /></UiLanguageProvider>);
    expect(screen.queryByText('0.60 USD')).not.toBeInTheDocument();
    expect(screen.getByText(/持仓页面已刷新/)).toBeInTheDocument();
  });
  it('does not accept an in-flight response against a refreshed ledger context', async () => {
    let finish!: (value: PerformanceReview) => void;
    api.reviewPerformance.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const view = mount({ revision: 1 }); open(); fill(); submit();
    view.rerender(<UiLanguageProvider><PerformancePanel accounts={accounts} ledgerContext={{ revision: 2 }} /></UiLanguageProvider>);
    await act(async () => finish(report()));
    expect(screen.queryByText('0.60 USD')).not.toBeInTheDocument();
    expect(screen.getByText(/持仓页面已刷新/)).toBeInTheDocument();
  });
  it('ignores a late response from the previous account', async () => {
    let finish!: (value: PerformanceReview) => void;
    api.reviewPerformance.mockImplementation((id: number) => id === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(report(item({ symbol: 'EUV' }))));
    mount(); open(); fill(); submit();
    fireEvent.change(screen.getByLabelText('复盘账户'), { target: { value: '2' } }); fill(); submit();
    await screen.findByText(/EUV · USD/);
    await act(async () => finish(report()));
    expect(screen.queryByText(/HAL · USD/)).not.toBeInTheDocument();
  });
  it('provides English controls without changing evidence semantics', async () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); mount();
    fireEvent.click(screen.getByRole('button', { name: 'Trading contribution versus holding' }));
    expect(screen.getByRole('button', { name: 'Calculate without writes' })).toBeInTheDocument();
    expect(screen.getByText(/Read-only review: no orders or cost edits/)).toBeInTheDocument();
  });
});
