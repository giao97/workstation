import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { CoreEntryPanel } from './CoreEntryPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { AllocationStatus, CoreEntryAssessment } from '../../types/portfolio';

const entry: CoreEntryAssessment = { symbol: 'QQQM', method: 'core-pullback-v1', state: 'candidate',
  asOf: '2026-10-02', evaluatedAt: '2026-10-05T14:00:00Z', sources: ['SyntheticFixture'],
  metrics: { close: 95, ma20: 99.45, drawdownPct: -5, ledgerCost: 90 }, reasons: ['pullback_and_close_not_lower'],
  checks: ['pullback_below_ma20'], limitations: [], executable: false, allocationReady: false, allocationAction: 'add' };
function mount(value?: Partial<CoreEntryAssessment>) {
  const status = { targets: [{ key: 'core', coreEntries: [{ ...entry, ...value }] }] } as AllocationStatus;
  return render(<UiLanguageProvider><CoreEntryPanel status={status} /></UiLanguageProvider>);
}
describe('CoreEntryPanel', () => {
  beforeEach(() => localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh'));
  it('separates price candidate, allocation and trading with no trade button', () => {
    mount(); expect(screen.getByText(/QQQM · 回撤候选/)).toBeInTheDocument();
    expect(screen.getByText(/目标、预算或现金条件尚不支持新增/)).toBeInTheDocument();
    expect(screen.getByText(/不按固定日期买/)).toBeInTheDocument();
    expect(screen.getByText('账本成本参考')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
  it('does not mislabel missing daily data as bearish conditions', () => {
    mount({ state: 'data_required', metrics: {}, asOf: null, reasons: ['need_latest_60_sessions'], checks: [] });
    expect(screen.getByText(/日线数据不足，不代表市场不适合买/)).toBeInTheDocument();
    expect(screen.getByText(/需最近已完成的连续 60 个交易日日线/)).toBeInTheDocument();
  });
  it('has an English research-only view', () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); mount({ allocationReady: true });
    expect(screen.getByText(/Pullback candidate; review required/)).toBeInTheDocument();
    expect(screen.getByText(/Unvalidated research screen/)).toBeInTheDocument();
  });
  it('does not render for old responses or theme targets', () => {
    render(<UiLanguageProvider><CoreEntryPanel status={{ targets: [{ key: 'theme' }] } as AllocationStatus} /></UiLanguageProvider>);
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
});
