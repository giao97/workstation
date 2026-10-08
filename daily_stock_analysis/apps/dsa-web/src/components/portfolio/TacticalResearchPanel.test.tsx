import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TacticalResearchPanel } from './TacticalResearchPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';

const preview = vi.hoisted(() => vi.fn());
vi.mock('../../api/tacticalResearch', () => ({ previewTactical: preview }));
const result = { state: 'scenario_only', executable: false, cash_required_usd: 503,
  remaining_cash_usd: 1530, planned_loss_usd: 28, tolerance_usd: 200, reasons: [] };
const mount = () => render(<UiLanguageProvider><TacticalResearchPanel /></UiLanguageProvider>);
function fill() {
  for (const [label, value] of [['本批共用可用美元现金', '2033'], ['现金核实时间（浏览器本地时间）', '2026-10-07T20:00'],
    ['每笔新增本金损失承受极限 %', '40'], ['代码', 'EUV'], ['新增本金 USD', '500'], ['逻辑失效计划损失 %', '5'],
    ['依据与买入确认条件', 'fixture trend confirmed'], ['逻辑失效与提前退出条件', 'fixture failure']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole('checkbox'));
}
describe('TacticalResearchPanel', () => {
  beforeEach(() => { vi.resetAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh'); });
  it('does not initialize cash or stop from historical profile and is read-only on mount', () => {
    mount(); expect(preview).not.toHaveBeenCalled();
    expect(screen.getByLabelText('本批共用可用美元现金')).toHaveValue(null);
    expect(screen.getByLabelText('逻辑失效计划损失 %')).toHaveValue(null);
    expect(screen.getByText(/不是默认止损/)).toBeInTheDocument();
  });
  it('sends unknown fees as null, uses explicit cash, invalidates results on edits', async () => {
    preview.mockResolvedValue(result); mount(); fill();
    fireEvent.click(screen.getByText('仅测算本批'));
    await screen.findByText('资金算术通过，仍不是交易许可');
    expect(preview.mock.calls[0][0]).toMatchObject({ available_cash_usd: 2033, loss_tolerance_pct: 40,
      cash_net_of_other_budgets: true, lots: [{ symbol: 'EUV', investment_usd: 500, planned_loss_pct: 5, round_trip_cost_usd: null }] });
    fireEvent.change(screen.getByLabelText('新增本金 USD'), { target: { value: '600' } });
    expect(screen.queryByText('资金算术通过，仍不是交易许可')).not.toBeInTheDocument();
  });
  it('does not show an old in-flight result after user edits inputs', async () => {
    let resolve!: (v: typeof result) => void;
    preview.mockImplementation(() => new Promise((r) => { resolve = r; })); mount(); fill();
    fireEvent.click(screen.getByText('仅测算本批')); await waitFor(() => expect(preview).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText('新增本金 USD'), { target: { value: '700' } });
    await act(async () => resolve(result));
    expect(screen.queryByText('资金算术通过，仍不是交易许可')).not.toBeInTheDocument();
  });
  it('adds candidates to one batch rather than allocating each its own cash pool', () => {
    mount(); fireEvent.click(screen.getByText('添加同池候选'));
    expect(screen.getAllByLabelText('新增本金 USD')).toHaveLength(2);
    expect(screen.getAllByLabelText('本批共用可用美元现金')).toHaveLength(1);
  });
  it('supports English without claiming execution readiness', () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); mount();
    expect(screen.getByText('New tactical lots · cash and risk scenarios')).toBeInTheDocument();
    expect(screen.getByText(/no entry validation/)).toBeInTheDocument();
  });
});
