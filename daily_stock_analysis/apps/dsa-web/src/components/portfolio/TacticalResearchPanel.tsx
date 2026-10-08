import { useRef, useState } from 'react';
import { previewTactical, type TacticalLot, type TacticalPreview } from '../../api/tacticalResearch';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';

const fieldClass = 'input-surface w-full rounded-lg border px-3 py-2 text-sm';
const blankLot = () => ({ symbol: '', investment: '', loss: '', fees: '', thesis: '', invalidation: '' });
const reasons: Record<string, [string, string]> = {
  cash_timestamp_stale_or_future: ['现金时点已超过 24 小时或在未来，请核实', 'Cash timestamp is stale or future; verify'],
  cash_must_exclude_other_budgets: ['现金未确认扣除其他预算', 'Exclude other budgets from available cash'],
  shared_cash_exceeded: ['本批合计超过同一现金池，请降低金额', 'Batch exceeds shared cash; reduce amounts'],
  all_in_costs_required: ['两边费用、价差与滑点未完整填写', 'Round-trip fees, spread and slippage are incomplete'],
  lot_risk_exceeded: ['有单笔计划损失超过承受极限', 'A lot exceeds its loss tolerance'],
};

export function TacticalResearchPanel() {
  const { language } = useUiLanguage(); const zh = language === 'zh';
  const [cash, setCash] = useState(''); const [asOf, setAsOf] = useState('');
  const [tolerance, setTolerance] = useState(''); const [confirmed, setConfirmed] = useState(false);
  const [lots, setLots] = useState([blankLot()]);
  const [result, setResult] = useState<TacticalPreview | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const change = (fn: () => void) => { revision.current++; setResult(null); setError(''); fn(); };
  const update = (index: number, key: keyof ReturnType<typeof blankLot>, value: string) =>
    change(() => setLots(lots.map((lot, i) => i === index ? { ...lot, [key]: value } : lot)));
  const money = (n: number | null) => n == null ? (zh ? '待核实' : 'Unknown') : `${n.toFixed(2)} USD`;
  return <Card><h2 className="font-semibold">{zh ? '新增战术仓 · 资金与风险测算' : 'New tactical lots · cash and risk scenarios'}</h2>
    <p className="text-xs text-secondary mt-2">{zh ? '与战略配置缺口分开：达到目标比例不自动禁止战术研究。此处只测算你输入的方案，不验证买点、不预留现金、不写入真实持仓，也不自动下单。' : 'Separate from strategic target gaps. This evaluates your inputs only: no entry validation, cash reservation, ledger changes or orders.'}</p>
    <form className="space-y-3 mt-3" onSubmit={async (e) => {
      e.preventDefault(); const current = ++revision.current; setBusy(true); setResult(null); setError('');
      try {
        const payloadLots: TacticalLot[] = lots.map((lot) => ({ symbol: lot.symbol.trim().toUpperCase(),
          investment_usd: Number(lot.investment), planned_loss_pct: Number(lot.loss),
          round_trip_cost_usd: lot.fees === '' ? null : Number(lot.fees), thesis: lot.thesis, invalidation: lot.invalidation }));
        const response = await previewTactical({ available_cash_usd: Number(cash), cash_as_of: new Date(asOf).toISOString(),
          cash_net_of_other_budgets: confirmed, loss_tolerance_pct: Number(tolerance), lots: payloadLots });
        if (revision.current === current) setResult(response);
      } catch { if (revision.current === current) setError(zh ? '测算失败，请检查输入与服务状态；未修改账本。' : 'Preview failed; check inputs and server. Ledger unchanged.'); }
      finally { setBusy(false); }
    }}>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="text-xs">{zh ? '本批共用可用美元现金' : 'Shared available USD cash'}<input className={fieldClass} required type="number" min="0" step="0.01" value={cash} onChange={(e) => change(() => setCash(e.target.value))} /></label>
        <label className="text-xs">{zh ? '现金核实时间（浏览器本地时间）' : 'Cash checked at (browser local time)'}<input className={fieldClass} required type="datetime-local" value={asOf} onChange={(e) => change(() => setAsOf(e.target.value))} /></label>
        <label className="text-xs">{zh ? '每笔新增本金损失承受极限 %' : 'Loss tolerance % of each new lot'}<input className={fieldClass} required type="number" min="0.01" max="99.99" step="0.01" value={tolerance} onChange={(e) => change(() => setTolerance(e.target.value))} /></label>
      </div>
      <label className="block text-xs"><input type="checkbox" checked={confirmed} onChange={(e) => change(() => setConfirmed(e.target.checked))} /> {zh ? '我确认现金已结算，并已扣除生活备用金、长期建仓预算、其他订单和方案占用（不是券商购买力）。' : 'Cash is settled and net of living reserves, core budgets and other orders/plans; not buying power.'}</label>
      {lots.map((lot, i) => <fieldset className="rounded-lg border border-border p-3 space-y-2" key={i}>
        <legend className="text-sm">{zh ? '新增批次' : 'New lot'} {i + 1}</legend>
        <div className="grid gap-2 md:grid-cols-4">{([
          ['symbol', zh ? '代码' : 'Symbol'], ['investment', zh ? '新增本金 USD' : 'Capital USD'],
          ['loss', zh ? '逻辑失效计划损失 %' : 'Planned loss %'], ['fees', zh ? '双边费用及滑点 USD（未知留空）' : 'All-in costs USD (blank if unknown)'],
        ] as const).map(([key, label]) => <label className="text-xs" key={key}>{label}<input className={fieldClass} required={key !== 'fees'}
          type={key === 'symbol' ? 'text' : 'number'} min={key === 'fees' ? '0' : '0.01'} step="0.01"
          value={lot[key]} onChange={(e) => update(i, key, e.target.value)} /></label>)}</div>
        <div className="grid gap-2 md:grid-cols-2">{(['thesis', 'invalidation'] as const).map((key) => <label className="text-xs" key={key}>{key === 'thesis' ? (zh ? '依据与买入确认条件' : 'Evidence and entry conditions') : (zh ? '逻辑失效与提前退出条件' : 'Invalidation and early exit')}
          <input className={fieldClass} required minLength={3} maxLength={500} value={lot[key]} onChange={(e) => update(i, key, e.target.value)} /></label>)}</div>
        {lots.length > 1 && <button type="button" className="text-xs" onClick={() => change(() => setLots(lots.filter((_, n) => n !== i)))}>{zh ? '移除本批' : 'Remove lot'}</button>}
      </fieldset>)}
      <p className="text-xs text-warning">{zh ? '例如 40% 仅是单笔新增本金的极端承受界限，不是默认止损，也不保证亏损封顶；逻辑失效可更早退出。相关标的的计划损失须合计评估，均价降低不等于赚到钱。' : 'For example, 40% is an extreme tolerance on new capital, not a default stop or guaranteed cap. Exit earlier on invalidation; correlated risks add up. Lower average cost is not profit.'}</p>
      <div className="flex gap-3"><button type="button" disabled={lots.length >= 10 || busy} onClick={() => change(() => setLots([...lots, blankLot()]))}>{zh ? '添加同池候选' : 'Add same-pool candidate'}</button>
        <button className="btn-primary px-3 py-2" type="submit" disabled={busy}>{zh ? '仅测算本批' : 'Preview batch only'}</button></div>
    </form>
    {error && <InlineAlert variant="danger" message={error} />}
    {result && <div className="mt-3 space-y-2" role="status">
      <p>{result.state === 'scenario_only' ? (zh ? '资金算术通过，仍不是交易许可' : 'Cash arithmetic passes; not trade authorization') : (zh ? '方案需调整 / 核实' : 'Revise / verify scenario')}</p>
      <p className="text-sm">{zh ? '含费用占用 / 剩余现金：' : 'Cash required / remaining: '}{money(result.cash_required_usd)} / {money(result.remaining_cash_usd)}</p>
      <p className="text-sm">{zh ? '计划损失合计 / 极端承受金额：' : 'Total planned loss / tolerance: '}{money(result.planned_loss_usd)} / {money(result.tolerance_usd)}</p>
      {result.reasons.map((r) => <p className="text-xs text-warning" key={r}>{reasons[r]?.[zh ? 0 : 1] ?? r}</p>)}
      <p className="text-xs text-secondary">{zh ? '该结果没有验证行情、买卖价差、券商规则或组合集中度；输入变化后失效，多页面预览不会互相预留额度。' : 'Quotes, spreads, broker rules and concentration remain unverified. Edits invalidate this preview; other previews do not reserve funds.'}</p>
    </div>}
  </Card>;
}
