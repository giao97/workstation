import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProfilePreviewPanel } from './ProfilePreviewPanel';
import type { ProfilePreview } from '../../types/portfolio';

const api = vi.hoisted(() => ({ previewProfile: vi.fn(), commitOpeningBalance: vi.fn() }));
vi.mock('../../api/portfolio', () => ({ portfolioApi: api }));
const result: ProfilePreview = { profileDate: '2026-10-02', status: 'reference', sourceHash: 'hash',
  market: 'us', currency: 'USD', canCommit: false, openingDate: null, cashBalance: null,
  positions: [{ symbol: 'QQQM', quantity: 12, quantityText: '12 股', costText: '约 294.65', costStatus: 'requires_confirmation' },
    { symbol: 'TSLA', quantity: null, quantityText: '待确认', costText: '待确认', costStatus: 'requires_confirmation' }] };
const file = { size: 50, text: () => Promise.resolve('profile document') };
const choose = () => fireEvent.change(screen.getByLabelText('选择投资档案'), { target: { files: [file] } });

describe('ProfilePreviewPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); api.previewProfile.mockResolvedValue(result); });
  it('does not automatically read or import and preserves incomplete rows in the draft', async () => {
    const draft = vi.fn(); render(<ProfilePreviewPanel zh onDraft={draft} />);
    expect(api.previewProfile).not.toHaveBeenCalled(); choose();
    await screen.findByText('QQQM');
    expect(draft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /替换期初表草稿/ }));
    expect(draft).toHaveBeenCalledWith(expect.objectContaining({ asOf: '', cashBalance: null,
      positions: [expect.objectContaining({ symbol: 'QQQM', quantity: 12, avgCost: NaN }),
        expect.objectContaining({ symbol: 'TSLA', quantity: NaN, avgCost: NaN })] }));
    expect(api.commitOpeningBalance).not.toHaveBeenCalled();
  });
  it('keeps stale files view-only', async () => {
    api.previewProfile.mockResolvedValue({ ...result, status: 'stale' });
    render(<ProfilePreviewPanel zh onDraft={vi.fn()} />); choose(); await screen.findByText('QQQM');
    expect(screen.getByRole('button', { name: /替换期初表草稿/ })).toBeDisabled();
  });
  it('requires a compatible selected account', async () => {
    render(<ProfilePreviewPanel zh />); choose(); await screen.findByText('QQQM');
    expect(screen.getByRole('button', { name: /替换期初表草稿/ })).toBeDisabled();
  });
  it('does not show an old response after selecting another file', async () => {
    let resolve!: (value: ProfilePreview) => void;
    api.previewProfile.mockReturnValueOnce(new Promise<ProfilePreview>((r) => { resolve = r; }));
    render(<ProfilePreviewPanel zh />); choose();
    await act(async () => { await Promise.resolve(); });
    choose(); await screen.findByText('QQQM');
    await act(async () => resolve({ ...result, positions: [{ ...result.positions[0], symbol: 'OLD' }] }));
    expect(screen.queryByText('OLD')).not.toBeInTheDocument();
  });
  it('renders English caution', () => {
    render(<ProfilePreviewPanel zh={false} />);
    expect(screen.getByText(/no ledger writes/)).toBeInTheDocument();
  });
});
