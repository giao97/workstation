import { useEffect, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';
import type { BudgetPeriod, PortfolioAccountItem, PortfolioTradeListItem } from '../../types/portfolio';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const zones = { cn: 'Asia/Shanghai', us: 'America/New_York', hk: 'Asia/Hong_Kong', jp: 'Asia/Tokyo', kr: 'Asia/Seoul', tw: 'Asia/Taipei' };
type Run = (action: () => Promise<unknown>) => Promise<void>;

function Field({ label, name, type = 'text', value, required = true, placeholder }: {
  label: string; name: string; type?: string; value?: string | number; required?: boolean; placeholder?: string;
}) {
  return <label className="text-xs">{label}<input className={inputClass} name={name} type={type}
    step={type === 'number' ? 'any' : undefined} min={type === 'number' ? '0' : undefined}
    defaultValue={value} required={required} placeholder={placeholder} /></label>;
}

export function BudgetPanel({ accounts, onSaved }: { accounts: PortfolioAccountItem[]; onSaved: () => Promise<void> }) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [expanded, setExpanded] = useState(false);
  const [accountId, setAccountId] = useState<number | null>(null);
  const account = accounts.find((a) => a.id === accountId) ?? accounts[0];
  return <Card>
    <button type="button" className="btn-secondary text-sm" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {zh ? '成交核实与月度预算' : 'Execution evidence and investment budgets'}
    </button>
    <p className="text-xs text-secondary mt-2">{zh ? '计划不是委托，委托不是成交；预算不是可用现金。本页不向券商发送任何订单。' : 'Plans are not orders; orders are not fills. Budget is not cash. No orders are sent to brokers.'}</p>
    {expanded && <div className="mt-3 space-y-3">
      <label className="text-xs">{zh ? '预算账户' : 'Budget account'}<select className={inputClass} value={account?.id ?? ''} onChange={(e) => setAccountId(Number(e.target.value))}>
        {!accounts.length && <option value="">{zh ? '请先创建账户' : 'Create an account first'}</option>}
        {accounts.map((a) => <option value={a.id} key={a.id}>{a.name} · {a.baseCurrency}</option>)}
      </select></label>
      {account && <Editor key={account.id} account={account} onSaved={onSaved} zh={zh} />}
    </div>}
  </Card>;
}

function Editor({ account, onSaved, zh }: { account: PortfolioAccountItem; onSaved: () => Promise<void>; zh: boolean }) {
  const [budgets, setBudgets] = useState<BudgetPeriod[]>([]);
  const [trades, setTrades] = useState<PortfolioTradeListItem[]>([]);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  useEffect(() => {
    let active = true;
    Promise.all([portfolioApi.listBudgets(account.id), portfolioApi.listTrades({ accountId: account.id, pageSize: 100 })])
      .then(([b, t]) => { if (active) { setBudgets(b.items); setTrades(t.items); } })
      .catch((e) => { if (active) setError(getParsedApiError(e).message); });
    return () => { active = false; };
  }, [account.id, revision]);
  const run: Run = async (action) => {
    setBusy(true); setError('');
    try { await action(); setRevision((r) => r + 1); await onSaved(); }
    catch (e) { setError(getParsedApiError(e).message); }
    finally { setBusy(false); }
  };
  const money = (value: number | null, currency: string) => value == null ? (zh ? '待核实' : 'Unknown') : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
  return <fieldset disabled={busy} className="space-y-4">
    {error && <InlineAlert variant="danger" message={error} />}
    <details><summary className="text-sm cursor-pointer">{zh ? '新建明确起止日期的投入预算' : 'Create an explicit-period budget'}</summary>
      <form className="mt-3 space-y-3" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(async () => {
        await portfolioApi.createBudget(account.id, { name: f.get('name'), currency: f.get('currency'), timezone: zones[account.market],
          start_date: f.get('start'), end_date: f.get('end'), amount: Number(f.get('amount')),
          symbols: String(f.get('symbols')).split(/[,，\s]+/).filter(Boolean), ledger_complete: false, request_key: requestKey });
        setRequestKey(crypto.randomUUID());
      }); }}>
        <p className="text-xs text-secondary">{zh ? `日期口径：${zones[account.market]}。不会自动续期、追补历史月份或产生入金。先录入，再核对本轮全部成交。` : `Dates use ${zones[account.market]}. No automatic renewal, catch-up or deposit. Reconcile all period trades after creation.`}</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Field label={zh ? '预算名称' : 'Name'} name="name" /><Field label={zh ? '预算币种' : 'Budget currency'} name="currency" value={account.baseCurrency} />
          <Field label={zh ? '总额度' : 'Limit'} name="amount" type="number" /><Field label={zh ? '起始日期' : 'Start date'} name="start" type="date" />
          <Field label={zh ? '结束日期（含）' : 'End date (inclusive)'} name="end" type="date" /><Field label={zh ? '共同使用预算的代码' : 'Symbols sharing this budget'} name="symbols" />
        </div><button className="btn-primary text-sm" type="submit">{zh ? '保存预算（不入金）' : 'Save budget (not a deposit)'}</button>
      </form>
    </details>
    {budgets.map((b) => <div key={b.id} className="rounded-xl border border-border p-3 space-y-3">
      <h3 className="font-semibold text-sm">{b.name} · {b.symbols.join(' / ')}</h3>
      <p className="text-xs text-secondary">{b.startDate} — {b.endDate} · {b.timezone} · {b.activePeriod ? (zh ? '本轮' : 'Current period') : (zh ? '非当前周期' : 'Outside current period')}</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
        <div>{zh ? '总额度' : 'Limit'}<p>{money(b.amount, b.currency)}</p></div><div>{zh ? '已核实支出' : 'Verified spending'}<p>{money(b.confirmedSpent, b.currency)}</p></div>
        <div>{zh ? '待成交预留' : 'Open-order reserve'}<p>{money(b.reservedAmount, b.currency)}</p></div><div>{zh ? '新增计划余额' : 'Remaining budget'}<p>{money(b.remainingAmount, b.currency)}</p></div>
      </div>
      {b.overBudgetAmount > 0 && <InlineAlert variant="warning" message={`${zh ? '已记录支出及预留超额：' : 'Recorded spending/reserve above limit: '}${money(b.overBudgetAmount, b.currency)}`} />}
      {!!b.unresolvedTradeIds.length && <p className="text-warning text-xs">{zh ? '待核实费用或换算的成交编号：' : 'Trades awaiting fee/conversion evidence: '}{b.unresolvedTradeIds.join(', ')}</p>}
      <button className="btn-secondary text-xs" type="button" onClick={() => void run(() => portfolioApi.confirmBudget(b.id, !b.ledgerComplete))}>
        {b.ledgerComplete ? (zh ? '发现漏记，取消完整性确认' : 'Revoke ledger completeness') : (zh ? '已核对本轮所有成交，确认完整' : 'Confirm all period trades are recorded')}
      </button>
      <details><summary className="text-xs cursor-pointer">{zh ? '核实成交换算 / 明确排除旧仓' : 'Verify conversion / exclude pre-existing allocation'}</summary>
        <form className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(() => portfolioApi.adjustBudgetTrade(b.id, Number(f.get('trade')), {
          fx_rate: f.get('rate') ? Number(f.get('rate')) : null, excluded: f.get('excluded') === 'on', reason: f.get('reason') })); }}>
          <Field label={zh ? '成交记录编号' : 'Trade ID'} name="trade" type="number" /><Field label={zh ? '每原币折合预算币种（已确认）' : 'Confirmed budget currency per trade currency'} name="rate" type="number" required={false} />
          <Field label={zh ? '依据 / 排除原因' : 'Evidence / exclusion reason'} name="reason" /><label className="text-xs flex items-center gap-2"><input name="excluded" type="checkbox" />{zh ? '明确不计入本轮' : 'Explicitly exclude from period'}</label>
          <button className="btn-secondary text-xs" type="submit">{zh ? '确认预算归属' : 'Confirm attribution'}</button>
        </form>
      </details>
      <IntentEditor budget={b} run={run} zh={zh} />
    </div>)}
    <details><summary className="text-sm cursor-pointer">{zh ? '核实近期成交费用与时间（最近100笔）' : 'Reconcile execution fees/time (latest 100)'}</summary>
      <p className="text-xs text-secondary my-2">{zh ? '成交价必须为未含费的真实成交单价，不填券商平均持仓成本。全部费用、税费经结单核对后才选“已核实”；未知时不要以0确认。' : 'Use actual execution prices, not broker average cost. Confirm fees/taxes only against the statement; unknown is not zero.'}</p>
      {trades.map((t) => <TradeEvidence key={`${t.id}-${t.revision}`} trade={t} run={run} zh={zh} />)}
    </details>
  </fieldset>;
}

function TradeEvidence({ trade: t, run, zh }: { trade: PortfolioTradeListItem; run: Run; zh: boolean }) {
  return <details className="border-t border-border py-2"><summary className="text-xs cursor-pointer">#{t.id} · {t.tradeDate} · {t.symbol} · {t.side} {t.quantity} @ {t.price} · {t.feeStatus ?? 'unknown'}</summary>
    <form className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(() => portfolioApi.reconcileTrade(t.id, {
      expected_revision: t.revision ?? 1, fee: Number(f.get('fee')), tax: Number(f.get('tax')), fee_status: f.get('status'), executed_at: f.get('time') || null, reason: f.get('reason') })); }}>
      <Field label={zh ? '费用合计' : 'Fees'} name="fee" type="number" value={t.fee} /><Field label={zh ? '税费合计' : 'Taxes'} name="tax" type="number" value={t.tax} />
      <label className="text-xs">{zh ? '费用证据' : 'Cost evidence'}<select name="status" defaultValue={t.feeStatus ?? 'unknown'} className={inputClass}><option value="unknown">{zh ? '未知' : 'Unknown'}</option><option value="estimated">{zh ? '估算' : 'Estimated'}</option><option value="confirmed">{zh ? '已核实' : 'Confirmed'}</option></select></label>
      <Field label={zh ? '成交时间（ISO格式，含时区）' : 'Execution time (ISO with offset)'} name="time" value={t.executedAt ?? ''} required={false} />
      <Field label={zh ? '核实依据' : 'Evidence'} name="reason" /><button className="btn-secondary text-xs" type="submit">{zh ? '保存核实记录' : 'Save evidence'}</button>
    </form>
  </details>;
}

function IntentEditor({ budget: b, run, zh }: { budget: BudgetPeriod; run: Run; zh: boolean }) {
  const [key, setKey] = useState(() => crypto.randomUUID());
  return <details><summary className="text-xs cursor-pointer">{zh ? '计划与手工委托反馈（不下单）' : 'Plans and manual order feedback (no trading)'}</summary>
    <form className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(async () => {
      await portfolioApi.createIntent(b.id, { symbol: f.get('symbol'), quantity: Number(f.get('quantity')), limit_price: Number(f.get('price')), fee_reserve: Number(f.get('fee')),
        fx_rate: Number(f.get('rate')), expires_at: f.get('expires'), request_key: key }); setKey(crypto.randomUUID());
    }); }}>
      <Field label={zh ? '计划标的' : 'Planned symbol'} name="symbol" /><Field label={zh ? '计划数量' : 'Planned quantity'} name="quantity" type="number" />
      <Field label={zh ? '计划限价（账户原币）' : 'Limit price (account currency)'} name="price" type="number" /><Field label={zh ? '费用预留（账户原币）' : 'Fee reserve (account currency)'} name="fee" type="number" />
      <Field label={zh ? '预算换算率（预算币种/原币）' : 'Budget currency per account currency'} name="rate" type="number" /><Field label={zh ? '有效期（ISO格式，含时区）' : 'Expiry (ISO with offset)'} name="expires" />
      <button type="submit" className="btn-secondary text-xs">{zh ? '只记录计划' : 'Record plan only'}</button>
    </form>
    {b.intents.map((i) => <form key={`${i.id}-${i.revision}`} className="border-t border-border mt-3 pt-2 space-y-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(() => portfolioApi.reportIntent(i.id, {
      expected_revision: i.revision, status: f.get('status'), reason: f.get('reason') })); }}>
      <p className="text-xs">#{i.id} {i.symbol} · {i.status} · {zh ? '已成交 / 剩余' : 'Filled / remaining'} {i.filledQuantity} / {i.remainingQuantity}</p>
      <p className="text-xs text-secondary">{zh ? '部分成交请在交易流水录入真实数量并填写此计划编号；重复反馈不等于新增成交。' : 'Record actual fills in the trade form with this intent ID. Status feedback never creates fills.'}</p>
      {i.remainingQuantity > 0 && <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Field label={zh ? '关联已录入的成交编号（不要重复录入）' : 'Link existing trade ID (do not duplicate)'} name="existing_trade" type="number" required={false} />
        <button className="btn-secondary text-xs" type="button" onClick={(e) => { const form = e.currentTarget.form; if (form) { const id = Number(new FormData(form).get('existing_trade')); if (id > 0) void run(() => portfolioApi.linkExistingFill(i.id, id)); } }}>{zh ? '只关联已有成交' : 'Link existing execution only'}</button>
      </div>}
      {['planned', 'submitted', 'pending_cancel'].includes(i.reportedStatus) && i.remainingQuantity > 0 && <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <label className="text-xs">{zh ? '券商状态反馈' : 'Broker status feedback'}<select className={inputClass} name="status">
          {i.reportedStatus !== 'submitted' && <option value="submitted">{zh ? '确认已提交 / 撤单被拒仍有效' : 'Submitted / cancellation rejected'}</option>}
          {i.reportedStatus === 'submitted' && <option value="pending_cancel">{zh ? '申请撤单，尚未确认' : 'Cancellation pending'}</option>}
          <option value="cancelled">{zh ? '确认已撤销剩余部分' : 'Remaining order cancelled'}</option><option value="expired">{zh ? '确认已失效，无剩余委托' : 'Expired, no remaining order'}</option>
        </select></label><Field label={zh ? '反馈依据' : 'Feedback evidence'} name="reason" />
        <button className="btn-secondary text-xs" type="submit">{zh ? '确认记录反馈' : 'Confirm feedback'}</button>
      </div>}
    </form>)}
  </details>;
}
