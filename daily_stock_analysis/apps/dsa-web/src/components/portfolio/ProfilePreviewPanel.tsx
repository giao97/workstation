import { useEffect, useRef, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import type { OpeningBalanceWrite, ProfilePreview } from '../../types/portfolio';

export function ProfilePreviewPanel({ zh, onDraft }: {
  zh: boolean; onDraft?: (draft: OpeningBalanceWrite) => void;
}) {
  const [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current += 1; }, []);
  const load = async (file?: File) => {
    const seq = ++sequence.current;
    setPreview(null); setError(''); setBusy(false);
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > 128 * 1024) throw new Error(zh ? '文件不能超过 128 KiB' : 'File must not exceed 128 KiB');
      const result = await portfolioApi.previewProfile(await file.text());
      if (seq === sequence.current) setPreview(result);
    } catch (e) {
      if (seq === sequence.current) setError(getParsedApiError(e).message);
    } finally { if (seq === sequence.current) setBusy(false); }
  };
  return <section className="rounded-xl border border-border p-3 space-y-3">
    <h3 className="text-sm font-semibold">{zh ? '投资档案预览（不写账本）' : 'Investment profile preview (no ledger writes)'}</h3>
    <p className="text-xs text-secondary">{zh
      ? '主动选择 Markdown 档案后，仅发送到本服务解析，不调用模型、不保存原文。只读取当前美股表，不读取历史、目标配置或现金。'
      : 'Select a Markdown profile to parse on this server only. No model calls or document storage. Only the current US table is read, not history, targets or cash.'}</p>
    <label className="text-sm">{zh ? '选择投资档案' : 'Select investment profile'}
      <input type="file" accept=".md,.txt" className="block mt-2" onChange={(e) => { void load(e.target.files?.[0]); }} />
    </label>
    {busy && <p role="status">{zh ? '正在解析…' : 'Parsing…'}</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {preview && <>
      <p className="text-sm">{zh ? '档案更新日期（不是期初日期）：' : 'Profile update date (not opening date): '}{preview.profileDate}</p>
      <div className="overflow-x-auto"><table className="text-sm w-full"><thead><tr>
        <th>{zh ? '标的' : 'Symbol'}</th><th>{zh ? '档案股数' : 'Profile quantity'}</th><th>{zh ? '成本原文（待核实）' : 'Cost text (unverified)'}</th>
      </tr></thead><tbody>{preview.positions.map((p) => <tr key={p.symbol}>
        <td>{p.symbol}</td><td>{p.quantityText}</td><td>{p.costText}</td>
      </tr>)}</tbody></table></div>
      <p className="text-xs text-warning">{zh
        ? '所有成本均待核对；未知股数不按零处理。现金、已结算资金、预算、期初日期均不推算。填写期初表前，请以同一已结束交易日的完整结单核对全部持仓。'
        : 'Verify every cost; unknown quantities are not zero. Cash, settled funds, budgets and opening date are not inferred. Reconcile all holdings against one completed-day statement.'}</p>
      {preview.status === 'stale' && <p role="alert">{zh ? '档案超过 7 天，仅供查看；请更新后重新选择。' : 'Profile is older than 7 days: view only. Update and select again.'}</p>}
      {!onDraft && <p>{zh ? '选择美元计价的美股账户后，才可带入期初草稿。' : 'Select a USD US account to prepare an opening draft.'}</p>}
      <button type="button" className="btn-secondary text-sm" disabled={!onDraft || preview.status !== 'reference' || busy}
        onClick={() => onDraft?.({ asOf: '', cashBalance: null, reportedMarketValue: null, reportedEquity: null,
          positions: preview.positions.map((p) => ({ symbol: p.symbol, quantity: p.quantity ?? NaN,
            avgCost: NaN, reportedMarketValue: null })) })}>
        {zh ? '替换期初表草稿，继续核对（不保存）' : 'Replace opening form draft for review (not saved)'}
      </button>
    </>}
  </section>;
}
