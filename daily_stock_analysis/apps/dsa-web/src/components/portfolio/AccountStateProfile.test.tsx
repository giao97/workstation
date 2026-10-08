import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { AccountStatePanel } from './AccountStatePanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import type { PortfolioAccountItem } from '../../types/portfolio';

const api = vi.hoisted(() => ({ getAccountState: vi.fn(), previewProfile: vi.fn(),
  previewOpeningBalance: vi.fn(), commitOpeningBalance: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const accounts = [1, 2].map((id) => ({ id, name: `Account ${id}`, market: 'us', baseCurrency: 'USD', isActive: true })) as PortfolioAccountItem[];
beforeEach(() => {
  vi.clearAllMocks(); localStorage.setItem('dsa.uiLanguage', 'zh');
  api.getAccountState.mockResolvedValue({ opening: null, funding: null });
  api.previewProfile.mockResolvedValue({ profileDate: '2026-10-02', status: 'reference',
    positions: [{ symbol: 'QQQM', quantity: 12, quantityText: '12 股', costText: '约 294.65' },
      { symbol: 'TSLA', quantity: null, quantityText: '待确认', costText: '待确认' }] });
});

it('loads every row into the existing form without cash/cost/date inference or writes, and isolates accounts', async () => {
  render(<UiLanguageProvider><AccountStatePanel accounts={accounts} onSaved={vi.fn()} /></UiLanguageProvider>);
  fireEvent.click(screen.getByRole('button', { name: '持仓基线与资金分层' }));
  await screen.findByText('建立期初持仓（仅空账本）');
  fireEvent.change(screen.getByLabelText('选择投资档案'), { target: { files: [{ size: 1, text: () => Promise.resolve('profile') }] } });
  await screen.findByText('QQQM');
  fireEvent.click(screen.getByRole('button', { name: /替换期初表草稿/ }));
  await screen.findByDisplayValue('QQQM');
  expect(screen.getByDisplayValue('TSLA')).toBeInTheDocument();
  expect(screen.getByLabelText('期初日期')).toHaveValue('');
  expect(screen.getByLabelText('确认账面现金（未知留空）')).toHaveValue(null);
  expect(screen.getAllByLabelText('已有单位成本').every((el) => (el as HTMLInputElement).value === '')).toBe(true);
  expect(screen.getAllByLabelText('股数 / 份额')[1]).toHaveValue(null);
  expect(api.previewOpeningBalance).not.toHaveBeenCalled(); expect(api.commitOpeningBalance).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('基线 / 资金账户'), { target: { value: '2' } });
  await waitFor(() => expect(api.getAccountState).toHaveBeenCalledWith(2));
  expect(screen.queryByDisplayValue('QQQM')).not.toBeInTheDocument();
});
