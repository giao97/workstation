import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AllocationReviewPanel } from './AllocationReviewPanel';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { AllocationReview, AllocationReviewList, AllocationStatus } from '../../types/portfolio';

const api = vi.hoisted(() => ({ getAllocationReviews: vi.fn(), saveAllocationReview: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const status = { planId: 1, planVersion: 2, targets: [{ key: 'core', name: 'Core' }, { key: 'other', name: 'Other' }] } as AllocationStatus;
const review = (patch: Partial<AllocationReview> = {}): AllocationReview => ({ id: 8, planId: 1, revision: 1,
  expectedPlanVersion: 2, expectedPreviousId: null, targetKey: 'core', requestKey: 'old', horizon: 'long_term',
  decision: 'maintain_plan', reason: 'Synthetic long-term reason', evidence: 'Synthetic evidence', nextCondition: 'Recheck cash',
  reviewDueAt: '2099-10-01T00:00:00Z', createdAt: '2026-09-30T00:00:00Z', state: 'active', authority: 'manual_unverified',
  targetSnapshot: {} as AllocationReview['targetSnapshot'], ...patch });
const page = (latest: AllocationReview[] = []): AllocationReviewList => ({ planVersion: 2, latest, items: latest, nextBeforeId: null });
const mount = () => render(<UiLanguageProvider><AllocationReviewPanel status={status} /></UiLanguageProvider>);
const open = () => fireEvent.click(screen.getByRole('button', { name: /长期配置 \/ 短线复核/ }));
const fill = () => {
  for (const [label, value] of [['本次理由', 'Synthetic wait'], ['新增证据 / 仍缺数据（含来源与时间）', 'Missing minute quotes'],
    ['下次复核条件 / 失效条件', 'Recheck reliable quote and cash'], ['最迟复核时间（本机时区）', '2099-10-01T22:00']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
};
const submit = () => fireEvent.submit(screen.getByRole('button', { name: '保存复核（不交易）' }).closest('form')!);

describe('AllocationReviewPanel', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.getAllocationReviews.mockResolvedValue(page()); api.saveAllocationReview.mockResolvedValue(review());
  });
  it('performs no reads or writes when collapsed', () => {
    mount(); expect(api.getAllocationReviews).not.toHaveBeenCalled(); expect(api.saveAllocationReview).not.toHaveBeenCalled();
  });
  it('shows independent current tracks, overdue and history without auto-renewal', async () => {
    api.getAllocationReviews.mockResolvedValue(page([review(), review({ id: 9, horizon: 'tactical', decision: 'wait',
      reviewDueAt: '2020-01-01T00:00:00Z', reason: 'Synthetic tactical reason' })]));
    mount(); open(); await screen.findByText(/等待 · 已到复核时间/);
    expect(screen.getByText(/配置计划维持 · 待按条件复核/)).toBeInTheDocument();
    expect(screen.getAllByText('Synthetic long-term reason')).toHaveLength(2);
    expect(api.saveAllocationReview).not.toHaveBeenCalled();
  });
  it('uses the selected track head and explicit deadline, not an order', async () => {
    api.getAllocationReviews.mockResolvedValue(page([review()])); mount(); open();
    await screen.findByLabelText('记录维度');
    fireEvent.change(screen.getByLabelText('记录维度'), { target: { value: 'tactical' } });
    fill(); submit();
    await waitFor(() => expect(api.saveAllocationReview).toHaveBeenCalledTimes(1));
    expect(api.saveAllocationReview).toHaveBeenCalledWith(1, expect.objectContaining({
      expectedPlanVersion: 2, expectedPreviousId: null, targetKey: 'core', horizon: 'tactical', decision: 'data_required',
      reviewDueAt: new Date('2099-10-01T22:00').toISOString(), requestKey: expect.any(String) }));
    await screen.findByRole('button', { name: '保存复核（不交易）' });
    expect(screen.getByLabelText('本次理由')).toHaveValue('');
  });
  it('keeps the same request key after an uncertain failure', async () => {
    api.saveAllocationReview.mockRejectedValue(new Error('Network failure'));
    mount(); open(); await screen.findByLabelText('本次理由'); fill(); submit();
    await screen.findByRole('button', { name: '保存复核（不交易）' }); submit();
    await waitFor(() => expect(api.saveAllocationReview).toHaveBeenCalledTimes(2));
    expect(api.saveAllocationReview.mock.calls[0][1]).toEqual(api.saveAllocationReview.mock.calls[1][1]);
  });
  it('isolates late data and clears the draft when switching assets', async () => {
    let finish!: (value: AllocationReviewList) => void;
    api.getAllocationReviews.mockImplementation((_id, target) => target === 'core'
      ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(page([review({ targetKey: 'other', reason: 'Other reason' })])));
    mount(); open(); fireEvent.change(screen.getByLabelText('复核资产'), { target: { value: 'other' } });
    await screen.findAllByText('Other reason'); await act(async () => finish(page([review()])));
    expect(screen.queryByText('Synthetic long-term reason')).not.toBeInTheDocument();
    expect(api.saveAllocationReview).not.toHaveBeenCalled();
  });
  it('blocks new writes when the plan version changed', async () => {
    api.getAllocationReviews.mockResolvedValue({ ...page([review({ state: 'plan_changed' })]), planVersion: 3 });
    mount(); open(); await screen.findByText('计划版本已变化，请重新加载配置计划后再记录。');
    expect(screen.queryByRole('button', { name: '保存复核（不交易）' })).not.toBeInTheDocument();
  });
  it('supports English labels and missing-data defaults', async () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en'); mount();
    fireEvent.click(screen.getByRole('button', { name: /Long-term \/ tactical review/ }));
    await screen.findByLabelText('Research decision (not an order)');
    expect(screen.getByLabelText('Research decision (not an order)')).toHaveValue('data_required');
    expect(screen.getAllByText('No review; no permission to trade')).toHaveLength(2);
  });
});
