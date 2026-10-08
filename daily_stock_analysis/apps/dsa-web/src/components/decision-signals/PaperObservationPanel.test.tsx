import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PaperObservationPanel } from './PaperObservationPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { PaperExperiment } from '../../api/paperObservations';

const api = vi.hoisted(() => ({ list: vi.fn(), capture: vi.fn(), evaluate: vi.fn() }));
vi.mock('../../api/paperObservations', () => ({ paperObservationsApi: api }));
const experiment: PaperExperiment = { id: 8, signal_id: 1, captured_at: '2026-09-29T16:00:00Z', snapshot_hash: 'a'.repeat(64),
  snapshot: { stock_code: 'EUV', action: 'reduce', status: 'active' },
  assumptions: { quantity: 20, baseline_shares: 105, protected_shares: 85, cash_usd: 1000, buy_fee_usd: 1.04, sell_fee_usd: 1.07, slippage_bps: 10, fee_note: 'Synthetic' } };
const content = (id = 1, market = 'us') => <UiLanguageProvider><PaperObservationPanel key={id} signalId={id} market={market} /></UiLanguageProvider>;
const open = () => fireEvent.click(screen.getByRole('button', { name: '独立模拟观察（不交易）' }));
const fill = () => {
  for (const [label, value] of [['模拟机动股数', '20'], ['模拟期初股数', '105'], ['模拟保护股数', '85'], ['模拟已结算现金 USD', '1000'],
    ['整笔买入总费用 USD（假设）', '1.04'], ['整笔卖出总费用 USD（假设）', '1.07'], ['每边不利滑点 bps（假设）', '10'], ['费用假设依据（不填账号或密钥）', 'Synthetic']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole('checkbox'));
};
const submit = () => fireEvent.submit(screen.getByRole('button', { name: '冻结建议与假设' }).closest('form')!);

describe('PaperObservationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.list.mockResolvedValue({ items: [] }); api.capture.mockResolvedValue(experiment);
  });
  it('does not fetch, capture, or evaluate while collapsed', () => {
    render(content()); expect(api.list).not.toHaveBeenCalled(); expect(api.capture).not.toHaveBeenCalled(); expect(api.evaluate).not.toHaveBeenCalled();
  });
  it('does not pretend A-share daily prices are supported', () => {
    render(content(1, 'cn')); open(); expect(screen.getByText(/首版仅支持/)).toBeInTheDocument(); expect(api.list).not.toHaveBeenCalled();
  });
  it('requires explicit blank assumptions without using real holdings as defaults', async () => {
    render(content()); open(); await screen.findByText(/尚无模拟归档/);
    expect(screen.getByLabelText('模拟期初股数')).toHaveValue(null);
    expect(screen.getByLabelText('整笔买入总费用 USD（假设）')).toBeRequired();
    fill(); submit();
    await waitFor(() => expect(api.capture).toHaveBeenCalledWith(1, expect.any(String), experiment.assumptions));
    expect(api.evaluate).not.toHaveBeenCalled();
  });
  it('keeps the request key across an uncertain retry', async () => {
    api.capture.mockRejectedValueOnce(new Error('Network')).mockResolvedValue(experiment);
    render(content()); open(); fill(); submit();
    await waitFor(() => expect(api.capture).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole('button', { name: '冻结建议与假设' })).not.toBeDisabled());
    submit(); await waitFor(() => expect(api.capture).toHaveBeenCalledTimes(2));
    expect(api.capture.mock.calls[0][1]).toBe(api.capture.mock.calls[1][1]);
  });
  it('preserves blocked, open, losing, and no-fill observations', async () => {
    api.list.mockResolvedValue({ items: [experiment] });
    api.evaluate.mockResolvedValue({ experiment, observed_at: experiment.captured_at, engine_version: 'paper-window-v1', items: [
      { horizon: 1, status: 'completed', relative_hold_pnl: -1.51, economic_cost_improvement_per_share: -0.014, opportunity_loss: 1.51 },
      { horizon: 3, status: 'open', relative_hold_pnl: -201.67, reason: 'exit_cash_insufficient' },
      { horizon: 5, status: 'blocked', reason: 'corporate_action_unsupported' },
      { horizon: 10, status: 'no_fill', reason: 'protected_shares', relative_hold_pnl: 0 },
    ] });
    render(content()); open(); fireEvent.click(await screen.findByRole('button', { name: '检查后续观察' }));
    await screen.findByText(/-201.67 USD/); expect(screen.getByText(/包含分红或拆股/)).toBeInTheDocument();
    expect(screen.getByText(/不能宣称成功降本/)).toBeInTheDocument(); expect(screen.getByText(/触及模拟底仓保护/)).toBeInTheDocument();
  });
  it('does not mix a late response from another signal', async () => {
    let finish!: (value: { items: PaperExperiment[] }) => void;
    api.list.mockImplementation((id: number) => id === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ items: [] }));
    const view = render(content()); open(); view.rerender(content(2)); open();
    await act(async () => finish({ items: [experiment] }));
    expect(screen.queryByText(/#8/)).not.toBeInTheDocument();
  });
  it('renders the English caution and entry', () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); render(content());
    fireEvent.click(screen.getByRole('button', { name: 'Independent paper observations (no trading)' }));
    expect(screen.getByText(/independent hypothetical capital/)).toBeInTheDocument();
  });
  it('requires explicit minute rules and submits a timezone-aware expiry', async () => {
    render(content()); open();
    fireEvent.change(screen.getByLabelText('模拟规则'), { target: { value: 'minute' } });
    fill();
    for (const [label, value] of [['入场边界 USD', '30'], ['回补/退出边界 USD', '29'], ['失效价 USD', '33'], ['截止时间（本机时区）', '2026-09-29T23:00']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    submit();
    await waitFor(() => expect(api.capture).toHaveBeenCalledWith(1, expect.any(String), experiment.assumptions,
      { entry_price: 30, exit_price: 29, invalidation_price: 33, expires_at: new Date('2026-09-29T23:00').toISOString() }));
    expect(api.evaluate).not.toHaveBeenCalled();
  });
  it('invalid expiry cannot become an unhandled submit or a backdated archive', async () => {
    render(content()); open(); fill();
    fireEvent.change(screen.getByLabelText('模拟规则'), { target: { value: 'minute' } });
    submit(); expect(await screen.findByText('请填写有效截止时间')).toBeInTheDocument();
    expect(api.capture).not.toHaveBeenCalled();
  });
  it('displays minute ambiguity as open, not as a 0-day successful backtest', async () => {
    const minute = { ...experiment, snapshot: { ...experiment.snapshot, paper_policy_version: 'paper-minute-v1',
      minute_rules: { entry_price: 30, exit_price: 29, invalidation_price: 33, expires_at: '2026-09-29T20:00:00Z' } } };
    api.list.mockResolvedValue({ items: [minute] });
    api.evaluate.mockResolvedValue({ experiment: minute, observed_at: experiment.captured_at, engine_version: 'paper-minute-v1', items: [
      { horizon: 0, status: 'open', relative_hold_pnl: -10, reason: 'minute_ambiguous_range',
        fills: [{ side: 'sell', timestamp: '2026-09-29T16:03:00Z', confirmation_bar: '2026-09-29T16:02:00Z', quantity: 20, price: 30, fee: 1.07 }] },
    ] });
    render(content()); open(); fireEvent.click(await screen.findByRole('button', { name: '检查后续观察' }));
    expect(await screen.findByText(/同分钟触及回补\/退出和失效区间/)).toBeInTheDocument();
    expect(screen.getByText(/单时段分钟回放 · 未恢复原股数/)).toBeInTheDocument();
    expect(screen.queryByText(/^0 个交易日/)).not.toBeInTheDocument();
    expect(screen.getByText(/sell 20 × 30 USD/)).toBeInTheDocument();
  });
});
