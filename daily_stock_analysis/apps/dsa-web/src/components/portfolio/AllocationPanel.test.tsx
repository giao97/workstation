import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AllocationPanel } from './AllocationPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { AllocationStatus } from '../../types/portfolio';

const api = vi.hoisted(() => ({
  getAllocationPlans: vi.fn(), getAllocationPlan: vi.fn(), saveAllocationPlan: vi.fn(), getAllocationStatus: vi.fn(),
}));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));

function status(name: string): AllocationStatus {
  return {
    planId: 1, planName: name, planVersion: 2, baseCurrency: 'CNY', targetTotalValue: 100000,
    accountId: null, asOf: '2026-09-25', ledgerComplete: false, cashReserveAmount: 10000,
    availableCash: null, totalRecommendedAdd: 0, dataQuality: 'partial', limitations: ['ledger_not_confirmed'],
    unassignedPositions: [], targets: [{
      key: 'stock', name, source: 'position', policy: 'buy_only', symbols: ['VOO'], targetPct: 100,
      sortOrder: 0, currentAmount: null, currentPct: null, targetAmount: 100000, gapAmount: null,
      allocationCap: 0, recommendedAmount: 0, action: 'review', reason: 'current_amount_unavailable',
      dataComplete: false, limitations: ['ledger_not_confirmed'],
    }],
  };
}

function mount() {
  return render(<UiLanguageProvider><AllocationPanel accounts={[]} snapshot={null} costMethod="fifo" /></UiLanguageProvider>);
}

describe('AllocationPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.getAllocationPlans.mockResolvedValue({ plans: [] });
  });

  it('keeps unknown balances visible and explains the review condition', async () => {
    api.getAllocationPlans.mockResolvedValue({ plans: [{ id: 1, name: 'Main' }] });
    api.getAllocationStatus.mockResolvedValue(status('核心仓'));
    mount();
    expect(await screen.findByText('核心仓')).toBeInTheDocument();
    expect(screen.getAllByText('待核实').length).toBeGreaterThan(1);
    expect(screen.getByText('先核实数据')).toBeInTheDocument();
    expect(screen.getByText('请确认该范围的持仓和现金已完整录入')).toBeInTheDocument();
    expect(api.getAllocationStatus).toHaveBeenCalledWith(1, { costMethod: 'fifo', includeRealtime: false });
  });

  it('saves manual unknown as null, with explicit opt-in controls off', async () => {
    api.saveAllocationPlan.mockResolvedValue({ id: 1 });
    api.getAllocationStatus.mockResolvedValue(status('存款'));
    mount();
    fireEvent.click(screen.getByRole('button', { name: '新建计划' }));
    fireEvent.change(screen.getByLabelText('计划名称'), { target: { value: '家庭配置' } });
    fireEvent.change(screen.getByLabelText('资产名称'), { target: { value: '存款' } });
    fireEvent.change(screen.getByLabelText('金额来源'), { target: { value: 'manual' } });
    fireEvent.change(screen.getByLabelText('目标占比 %'), { target: { value: '100' } });
    expect(screen.getByLabelText('当前余额（未知留空）')).toHaveValue(null);
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }));
    await waitFor(() => expect(api.saveAllocationPlan).toHaveBeenCalled());
    expect(api.saveAllocationPlan.mock.calls[0][0]).toMatchObject({
      ledgerComplete: false, includeInReports: false, accountId: null,
      targets: [expect.objectContaining({ source: 'manual', currentAmount: null })],
    });
  });

  it('discards late results from a previously selected plan', async () => {
    api.getAllocationPlans.mockResolvedValue({ plans: [{ id: 1, name: 'One' }, { id: 2, name: 'Two' }] });
    let finishFirst!: (value: AllocationStatus) => void;
    api.getAllocationStatus.mockImplementation((id: number) => id === 1
      ? new Promise<AllocationStatus>((resolve) => { finishFirst = resolve; })
      : Promise.resolve(status('新计划资产')));
    mount();
    await waitFor(() => expect(api.getAllocationStatus).toHaveBeenCalledWith(1, expect.anything()));
    fireEvent.change(screen.getByLabelText('配置计划'), { target: { value: '2' } });
    expect(await screen.findByText('新计划资产')).toBeInTheDocument();
    await act(async () => { finishFirst(status('旧计划资产')); });
    expect(screen.queryByText('旧计划资产')).not.toBeInTheDocument();
  });

  it('labels reference caps and preserves the quote and FX dates', async () => {
    const result = status('周末配置');
    Object.assign(result.targets[0], { action: 'add', recommendedAmount: 1000, isEstimate: true,
      referenceNotes: ['close_reference:VOO:2026-09-25', 'fx_reference:USD/CNY:2026-09-25'],
      limitations: [], reason: 'below_target' });
    api.getAllocationPlans.mockResolvedValue({ plans: [{ id: 1, name: 'Main' }] });
    api.getAllocationStatus.mockResolvedValue(result);
    mount();
    expect(await screen.findByText('估算参考，非实时指令')).toBeInTheDocument();
    expect(screen.getByText(/最近收盘参考价 \(VOO · 2026-09-25\)/)).toBeInTheDocument();
    expect(screen.getByText(/日线汇率估算 \(USD\/CNY · 2026-09-25\)/)).toBeInTheDocument();
    expect(screen.getByText('1,000.00 CNY')).toBeInTheDocument();
  });

  it('subtotals the existing funding allocation without reevaluating the cash budget', async () => {
    const result = status('美股');
    Object.assign(result, { confirmedCash: 500, fundingAccounts: [{ accountId: 1, currency: 'USD',
      plannedDeposit: 30000, plannedDepositDate: null, cashConfirmed: true, confirmedCashCap: 500 }] });
    Object.assign(result.targets[0], { targetAmount: 250000, currentAmount: 70000, gapAmount: 180000, fundedAmount: 500 });
    result.targets.push({ ...result.targets[0], key: 'gold', name: '黄金', targetAmount: 50000,
      currentAmount: 55000, gapAmount: -5000, fundedAmount: 0 });
    api.getAllocationPlans.mockResolvedValue({ plans: [{ id: 1, name: 'Main' }] });
    api.getAllocationStatus.mockResolvedValue(result);
    mount();
    fireEvent.click(await screen.findByLabelText('汇总 美股'));
    fireEvent.click(screen.getByLabelText('汇总 黄金'));
    expect(screen.getByTestId('allocation-group-summary')).toHaveTextContent('目标 300,000.00 CNY');
    expect(screen.getByTestId('allocation-group-summary')).toHaveTextContent('现金覆盖合计 500.00 CNY');
    expect(screen.getByText(/尚未到账的计划追加：#1 30,000.00 USD/)).toBeInTheDocument();
    expect(api.getAllocationStatus).toHaveBeenCalledTimes(1);
  });
});
