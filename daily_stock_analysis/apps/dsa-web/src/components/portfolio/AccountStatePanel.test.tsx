import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountStatePanel } from './AccountStatePanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { AccountState, PortfolioAccountItem } from '../../types/portfolio';

const api = vi.hoisted(() => ({ getAccountState: vi.fn(), previewOpeningBalance: vi.fn(),
  commitOpeningBalance: vi.fn(), saveFunding: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const accounts = [1, 2].map((id) => ({ id, name: `Account ${id}`, market: 'us', baseCurrency: 'USD',
  broker: 'Test', isActive: true, createdAt: '', updatedAt: '' })) as PortfolioAccountItem[];
const state = (id = 1): AccountState => ({ accountId: id, currency: 'USD', opening: null, funding: null,
  cashConfirmed: false, confirmedCashCap: null, disclosures: [] });
const saved = vi.fn().mockResolvedValue(undefined);
const mount = () => render(<UiLanguageProvider><AccountStatePanel accounts={accounts} onSaved={saved} /></UiLanguageProvider>);
async function open() {
  fireEvent.click(screen.getByRole('button', { name: '持仓基线与资金分层' }));
  await screen.findByText('建立期初持仓（仅空账本）');
}
function fillPosition() {
  fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'EUV' } });
  fireEvent.change(screen.getByLabelText('股数 / 份额'), { target: { value: '105' } });
  fireEvent.change(screen.getByLabelText('已有单位成本'), { target: { value: '29.46' } });
}

describe('AccountStatePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.getAccountState.mockImplementation((id: number) => Promise.resolve(state(id)));
    api.previewOpeningBalance.mockResolvedValue({ canCommit: false, previewToken: 'token',
      detailMarketValue: 8191.35, marketValueDifference: 25.65, equityLessMarketValue: 1514,
      equityDifference: null, limitations: ['opening_cash_balance_required_before_commit'] });
    api.commitOpeningBalance.mockResolvedValue({ accountId: 1, created: true });
    api.saveFunding.mockResolvedValue({ id: 1 });
  });
  it('does not load or write account state until the panel is opened', () => {
    mount();
    expect(api.getAccountState).not.toHaveBeenCalled();
    expect(api.commitOpeningBalance).not.toHaveBeenCalled();
  });
  it('allows preview with unknown cash but does not allow confirmation', async () => {
    mount(); await open(); fillPosition();
    fireEvent.click(screen.getByRole('button', { name: '预览与对账' }));
    expect(await screen.findByText(/总市值减明细差额（不分摊）：25.65 USD/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '核对无误，确认建立期初' })).toBeDisabled();
    expect(api.previewOpeningBalance).toHaveBeenCalledWith(1, expect.objectContaining({ cashBalance: null }));
    expect(api.commitOpeningBalance).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('确认账面现金（未知留空）'), { target: { value: '1400' } });
    expect(screen.queryByRole('button', { name: '核对无误，确认建立期初' })).not.toBeInTheDocument();
  });
  it('requires a preview and explicit confirmation before writing', async () => {
    api.previewOpeningBalance.mockResolvedValue({ canCommit: true, previewToken: 'confirmed-preview', limitations: [] });
    mount(); await open(); fillPosition();
    fireEvent.change(screen.getByLabelText('确认账面现金（未知留空）'), { target: { value: '1400' } });
    fireEvent.click(screen.getByRole('button', { name: '预览与对账' }));
    const confirm = await screen.findByRole('button', { name: '核对无误，确认建立期初' });
    expect(api.commitOpeningBalance).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    await waitFor(() => expect(api.commitOpeningBalance).toHaveBeenCalledWith(1,
      expect.objectContaining({ cashBalance: 1400, positions: [expect.objectContaining({ quantity: 105 })] }), 'confirmed-preview'));
    await waitFor(() => expect(saved).toHaveBeenCalled());
  });
  it('saves planned funding separately with unknown settled and available cash', async () => {
    mount(); await open();
    fireEvent.change(screen.getByLabelText('计划追加金额（尚未到账）'), { target: { value: '30000' } });
    fireEvent.click(screen.getByRole('button', { name: '保存资金确认' }));
    await waitFor(() => expect(api.saveFunding).toHaveBeenCalledWith(1, expect.objectContaining({
      plannedDeposit: 30000, settledCash: null, availableCash: null,
    })));
    expect(api.commitOpeningBalance).not.toHaveBeenCalled();
  });
  it('ignores a late response from a previously selected account', async () => {
    let finish!: (value: AccountState) => void;
    api.getAccountState.mockImplementation((id: number) => id === 1
      ? new Promise<AccountState>((resolve) => { finish = resolve; }) : Promise.resolve(state(id)));
    mount();
    fireEvent.click(screen.getByRole('button', { name: '持仓基线与资金分层' }));
    await waitFor(() => expect(api.getAccountState).toHaveBeenCalledWith(1));
    fireEvent.change(screen.getByLabelText('基线 / 资金账户'), { target: { value: '2' } });
    await screen.findByText('建立期初持仓（仅空账本）');
    await act(async () => { finish({ ...state(), opening: { asOf: '2026-09-01', cashBalance: 99,
      reportedEquity: null, reportedMarketValue: null, positions: [{ symbol: 'OLD', quantity: 1, avgCost: 1, reportedMarketValue: null }] } }); });
    expect(screen.queryByText(/OLD ×/)).not.toBeInTheDocument();
    fillPosition();
    fireEvent.click(screen.getByRole('button', { name: '预览与对账' }));
    await waitFor(() => expect(api.previewOpeningBalance).toHaveBeenCalledWith(2, expect.anything()));
  });
});
