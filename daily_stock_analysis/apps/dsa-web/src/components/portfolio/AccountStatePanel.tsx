import { useEffect, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';
import { ProfilePreviewPanel } from './ProfilePreviewPanel';
import type { AccountState, FundingWrite, OpeningBalanceWrite, OpeningPreview, PortfolioAccountItem } from '../../types/portfolio';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const localDate = (offset = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function AccountStatePanel({ accounts, onSaved }: {
  accounts: PortfolioAccountItem[]; onSaved: () => Promise<void>;
}) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [expanded, setExpanded] = useState(false);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [draft, setDraft] = useState<OpeningBalanceWrite | undefined>();
  const [draftAccountId, setDraftAccountId] = useState<number | null>(null);
  const [draftRevision, setDraftRevision] = useState(0);
  const account = accounts.find((a) => a.id === accountId) ?? accounts[0];
  return <Card>
    <button className="btn-secondary text-sm" type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
      {zh ? '持仓基线与资金分层' : 'Opening inventory and funding'}
    </button>
    <p className="text-xs text-secondary mt-2">{zh ? '已有持仓不是新买入；计划追加资金不等于已到账现金。先预览核对，再确认写入。' : 'Existing inventory is not a new trade. Planned funding is not cash. Preview and reconcile before confirming.'}</p>
    {expanded && <div className="mt-3 space-y-3">
      <label className="text-xs">{zh ? '基线 / 资金账户' : 'Inventory / funding account'}
        <select className={inputClass} value={account?.id ?? ''} onChange={(e) => { setAccountId(Number(e.target.value)); setDraft(undefined); }}>
          {!accounts.length && <option value="">{zh ? '请先创建账户' : 'Create an account first'}</option>}
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.baseCurrency}</option>)}
        </select>
      </label>
      <ProfilePreviewPanel key={`profile-${account?.id ?? 'none'}`} zh={zh}
        onDraft={account?.market === 'us' && account.baseCurrency === 'USD' ? (value) => {
          setDraft(value); setDraftAccountId(account.id); setDraftRevision((v) => v + 1);
        } : undefined} />
      {account && <AccountEditor key={`${account.id}-${draftRevision}`} account={account} onSaved={onSaved} zh={zh} draft={draftAccountId === account.id ? draft : undefined} />}
    </div>}
  </Card>;
}

function AccountEditor({ account, onSaved, zh, draft }: { account: PortfolioAccountItem; onSaved: () => Promise<void>; zh: boolean; draft?: OpeningBalanceWrite }) {
  const [state, setState] = useState<AccountState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [preview, setPreview] = useState<OpeningPreview | null>(null);
  const [opening, setOpening] = useState<OpeningBalanceWrite>(draft ?? { asOf: localDate(-1), cashBalance: null,
    reportedMarketValue: null, reportedEquity: null,
    positions: [{ symbol: '', quantity: NaN, avgCost: NaN, reportedMarketValue: null }] });
  const [funding, setFunding] = useState<FundingWrite>({ asOf: localDate(), settledCash: null,
    availableCash: null, plannedDeposit: null, plannedDepositDate: null });
  useEffect(() => {
    let active = true;
    portfolioApi.getAccountState(account.id).then((value) => {
      if (!active) return;
      setState(value); setLoaded(true);
      if (value.funding) setFunding({ ...value.funding });
    }).catch((err) => { if (active) setError(getParsedApiError(err).message); });
    return () => { active = false; };
  }, [account.id, revision]);

  const money = (v: number | null | undefined) => v == null ? (zh ? '待确认' : 'Unknown') : `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${account.baseCurrency}`;
  const edit = (patch: Partial<OpeningBalanceWrite>) => { setOpening({ ...opening, ...patch }); setPreview(null); };
  const numberInput = (label: string, value: number | null, update: (v: number | null) => void, required = false) =>
    <label className="text-xs">{label}<input className={inputClass} type="number" min="0" step="any" required={required}
      value={value == null || !Number.isFinite(value) ? '' : value}
      onChange={(e) => update(e.target.value === '' ? null : Number(e.target.value))} /></label>;
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await action(); } catch (err) { setError(getParsedApiError(err).message); }
    finally { setBusy(false); }
  };
  const warnings: Record<string, string> = {
    opening_cash_balance_required_before_commit: '确认账面现金后才能建立基线；不以净值差额推算。',
    existing_ledger_requires_manual_reconciliation: '已有交易或现金记录，需先人工对账，不能重复建立基线。',
    opening_balance_already_exists: '已有期初基线，不允许直接覆盖。',
    historical_realized_pnl_unavailable: '不还原期初之前的已实现收益。',
    opening_fifo_lots_aggregated: '期初每只标的按平均成本作为合并批次，不等同于券商历史 FIFO 批次。',
  };
  return <div className="space-y-4">
    {error && <InlineAlert variant="danger" message={error} />}
    {loaded && !state?.opening && <form onSubmit={(e) => { e.preventDefault(); void run(async () => {
      setPreview(await portfolioApi.previewOpeningBalance(account.id, opening));
    }); }}>
      <fieldset disabled={busy} className="space-y-3">
        <h3 className="text-sm font-semibold">{zh ? '建立期初持仓（仅空账本）' : 'Opening inventory (empty ledgers only)'}</h3>
        <p className="text-xs text-secondary">{zh ? `所有金额以 ${account.baseCurrency} 计价；日期为已结束的一天，之后仅录入更晚的成交。未知现金可预览，但不能确认写入。` : `Amounts in ${account.baseCurrency}. Use a completed end-of-day date; only later events may be added. Unknown cash permits preview, not commit.`}</p>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="text-xs">{zh ? '期初日期' : 'Opening date'}<input type="date" required max={localDate(-1)} className={inputClass} value={opening.asOf} onChange={(e) => edit({ asOf: e.target.value })} /></label>
          {numberInput(zh ? '确认账面现金（未知留空）' : 'Book cash (blank if unknown)', opening.cashBalance, (v) => edit({ cashBalance: v }))}
          {numberInput(zh ? '券商持仓总市值' : 'Reported total market value', opening.reportedMarketValue, (v) => edit({ reportedMarketValue: v }))}
          {numberInput(zh ? '券商账户净值' : 'Reported account equity', opening.reportedEquity, (v) => edit({ reportedEquity: v }))}
        </div>
        {opening.positions.map((p, i) => <div key={i} className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
          <label className="text-xs">{zh ? '标的代码' : 'Symbol'}<input required maxLength={16} className={inputClass} value={p.symbol} onChange={(e) => edit({ positions: opening.positions.map((x, j) => j === i ? { ...x, symbol: e.target.value } : x) })} /></label>
          {numberInput(zh ? '股数 / 份额' : 'Quantity', p.quantity, (v) => edit({ positions: opening.positions.map((x, j) => j === i ? { ...x, quantity: v ?? NaN } : x) }), true)}
          {numberInput(zh ? '已有单位成本' : 'Existing unit cost', p.avgCost, (v) => edit({ positions: opening.positions.map((x, j) => j === i ? { ...x, avgCost: v ?? NaN } : x) }), true)}
          {numberInput(zh ? '报送分项市值' : 'Reported position value', p.reportedMarketValue, (v) => edit({ positions: opening.positions.map((x, j) => j === i ? { ...x, reportedMarketValue: v } : x) }))}
          <button type="button" className="btn-secondary text-sm" disabled={opening.positions.length === 1} onClick={() => edit({ positions: opening.positions.filter((_, j) => i !== j) })}>{zh ? '移除此行' : 'Remove row'}</button>
        </div>)}
        <div className="flex gap-2 flex-wrap"><button type="button" className="btn-secondary text-sm" onClick={() => edit({ positions: [...opening.positions, { symbol: '', quantity: NaN, avgCost: NaN, reportedMarketValue: null }] })}>{zh ? '添加持仓行' : 'Add position'}</button>
          <button type="submit" className="btn-primary text-sm">{zh ? '预览与对账' : 'Preview and reconcile'}</button></div>
      </fieldset>
    </form>}
    {preview && !state?.opening && <div className="rounded-xl border border-border p-3 space-y-2 text-sm">
      <p>{zh ? '明细市值合计：' : 'Position value sum: '}{money(preview.detailMarketValue)}</p>
      <p>{zh ? '总市值减明细差额（不分摊）：' : 'Unallocated market value difference: '}{money(preview.marketValueDifference)}</p>
      <p>{zh ? '净值减持仓市值（不等于可用现金）：' : 'Equity minus holdings (not available cash): '}{money(preview.equityLessMarketValue)}</p>
      <p>{zh ? '净值减持仓及确认现金差额：' : 'Equity reconciliation difference: '}{money(preview.equityDifference)}</p>
      {preview.limitations.map((code) => <p className="text-xs text-warning" key={code}>{zh ? warnings[code] ?? code : code}</p>)}
      <button className="btn-primary text-sm" disabled={busy || !preview.canCommit} type="button" onClick={() => void run(async () => {
        await portfolioApi.commitOpeningBalance(account.id, opening, preview.previewToken);
        setPreview(null); setRevision((v) => v + 1); await onSaved();
      })}>{zh ? '核对无误，确认建立期初' : 'Confirm opening inventory'}</button>
    </div>}
    {state?.opening && <div className="rounded-xl border border-border p-3 text-sm space-y-2">
      <p>{zh ? '已确认期初：' : 'Confirmed opening: '}{state.opening.asOf} · {zh ? '账面现金 ' : 'Book cash '}{money(state.opening.cashBalance)}</p>
      <p>{state.opening.positions.map((p) => `${p.symbol} × ${p.quantity}`).join(' · ')}</p>
      <p className="text-xs text-secondary">{zh ? '基线不可直接覆盖；期初前已实现收益及真实 FIFO 批次未知。' : 'Opening inventory is immutable. Earlier realized P&L and original FIFO lots are unknown.'}</p>
    </div>}
    {loaded && <form onSubmit={(e) => { e.preventDefault(); void run(async () => {
      await portfolioApi.saveFunding(account.id, funding); setRevision((v) => v + 1); await onSaved();
    }); }}><fieldset disabled={busy} className="space-y-3">
      <h3 className="text-sm font-semibold">{zh ? '资金分层（不生成入金流水）' : 'Funding layers (does not create a deposit)'}</h3>
      <p className="text-xs text-secondary">{zh ? '只填写券商核实的自有现金，不含融资购买力。跨日或账本变化后须重新确认；计划追加额不会自动到账。' : 'Use verified own cash, excluding margin buying power. Reconfirm after a new date or ledger change. Planned deposits never become cash automatically.'}</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="text-xs">{zh ? '资金核实日期' : 'Cash observation date'}<input type="date" required max={localDate()} className={inputClass} value={funding.asOf} onChange={(e) => setFunding({ ...funding, asOf: e.target.value })} /></label>
        {numberInput(zh ? '已结算现金（未知留空）' : 'Settled cash (blank if unknown)', funding.settledCash, (v) => setFunding({ ...funding, settledCash: v }))}
        {numberInput(zh ? '可买入自有现金（未知留空）' : 'Own cash available to buy (blank if unknown)', funding.availableCash, (v) => setFunding({ ...funding, availableCash: v }))}
        {numberInput(zh ? '计划追加金额（尚未到账）' : 'Planned deposit (not received)', funding.plannedDeposit, (v) => setFunding({ ...funding, plannedDeposit: v }))}
        <label className="text-xs">{zh ? '计划到账日期（可留空）' : 'Planned deposit date (optional)'}<input type="date" className={inputClass} value={funding.plannedDepositDate ?? ''} onChange={(e) => setFunding({ ...funding, plannedDepositDate: e.target.value || null })} /></label>
      </div>
      <p className="text-xs">{zh ? '当前资金确认上限（仍受账面余额及预留限制）：' : 'Cash confirmation cap (ledger and reserves still apply): '}{money(state?.confirmedCashCap)}</p>
      <button type="submit" className="btn-primary text-sm">{zh ? '保存资金确认' : 'Save funding confirmation'}</button>
    </fieldset></form>}
  </div>;
}
