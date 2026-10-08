import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BudgetPanel } from './BudgetPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { BudgetPeriod, PortfolioAccountItem } from '../../types/portfolio';

const api = vi.hoisted(() => ({ listBudgets: vi.fn(), listTrades: vi.fn(), createBudget: vi.fn(),
  confirmBudget: vi.fn(), adjustBudgetTrade: vi.fn(), createIntent: vi.fn(), reportIntent: vi.fn(), reconcileTrade: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const accounts = [1, 2].map((id) => ({ id, name: `Account ${id}`, market: 'us', baseCurrency: 'USD', isActive: true })) as PortfolioAccountItem[];
const budget = (patch: Partial<BudgetPeriod> = {}): BudgetPeriod => ({ id: 1, accountId: 1, name: 'Core budget', currency: 'CNY', timezone: 'America/New_York',
  startDate: '2026-09-28', endDate: '2026-10-27', symbols: ['VOO', 'QQQM'], amount: 10000, ledgerComplete: false, activePeriod: true,
  confirmedSpent: 0, reservedAmount: 0, nativeReserved: 0, remainingAmount: null, overBudgetAmount: 0,
  unresolvedTradeIds: [9], trades: [], intents: [], ...patch });
const mount = () => render(<UiLanguageProvider><BudgetPanel accounts={accounts} onSaved={async () => {}} /></UiLanguageProvider>);
const open = () => fireEvent.click(screen.getByRole('button', { name: '成交核实与月度预算' }));

describe('BudgetPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.listBudgets.mockResolvedValue({ items: [budget()] }); api.listTrades.mockResolvedValue({ items: [] });
  });
  it('does not read or write financial state while collapsed', () => {
    mount(); expect(api.listBudgets).not.toHaveBeenCalled(); expect(api.createBudget).not.toHaveBeenCalled();
  });
  it('shows unknown, not zero, and requires explicit completeness confirmation', async () => {
    mount(); open(); await screen.findByText('Core budget · VOO / QQQM');
    expect(screen.getByText('待核实')).toBeInTheDocument();
    expect(api.confirmBudget).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('已核对本轮所有成交，确认完整'));
    await waitFor(() => expect(api.confirmBudget).toHaveBeenCalledWith(1, true));
  });
  it('does not create fills or release reserves for an expired unconfirmed order', async () => {
    api.listBudgets.mockResolvedValue({ items: [budget({ reservedAmount: 4900, intents: [{ id: 8, symbol: 'VOO', status: 'expired_pending_confirmation',
      reportedStatus: 'submitted', revision: 2, quantity: 2, filledQuantity: 1, remainingQuantity: 1, reservedAmount: 4900, expiresAt: '2026-09-29T20:00:00Z' }] })] });
    mount(); open(); await screen.findByText(/expired_pending_confirmation/);
    expect(api.reportIntent).not.toHaveBeenCalled(); expect(api.reconcileTrade).not.toHaveBeenCalled();
    expect(screen.getByText('4,900 CNY')).toBeInTheDocument();
  });
  it('ignores a late response from the previously selected account', async () => {
    let finish!: (value: { items: BudgetPeriod[] }) => void;
    api.listBudgets.mockImplementation((id: number) => id === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ items: [budget({ name: 'Second account' })] }));
    mount(); open(); fireEvent.change(screen.getByLabelText('预算账户'), { target: { value: '2' } });
    await screen.findByText('Second account · VOO / QQQM');
    await act(async () => finish({ items: [budget()] }));
    expect(screen.queryByText('Core budget · VOO / QQQM')).not.toBeInTheDocument();
  });
  it('submits exact-period shared budget without funding or completeness assumptions', async () => {
    api.createBudget.mockResolvedValue({ id: 2 }); mount(); open();
    await screen.findByText('Core budget · VOO / QQQM');
    for (const [label, value] of [['预算名称', 'Monthly core'], ['预算币种', 'CNY'], ['总额度', '10000'], ['起始日期', '2026-09-28'], ['结束日期（含）', '2026-10-27'], ['共同使用预算的代码', 'QQQM, VOO']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.submit(screen.getByRole('button', { name: '保存预算（不入金）', hidden: true }).closest('form')!);
    await waitFor(() => expect(api.createBudget).toHaveBeenCalledWith(1, expect.objectContaining({
      amount: 10000, symbols: ['QQQM', 'VOO'], timezone: 'America/New_York', ledger_complete: false, currency: 'CNY' })));
  });
});
