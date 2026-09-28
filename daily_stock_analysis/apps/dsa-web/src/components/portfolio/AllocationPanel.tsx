import { useEffect, useRef, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';
import type {
  AllocationPlan, AllocationPlanWrite, AllocationStatus, AllocationTarget,
  PortfolioAccountItem, PortfolioCostMethod, PortfolioSnapshotResponse,
} from '../../types/portfolio';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';

function blankTarget(index: number): AllocationTarget {
  return { key: `asset_${Date.now()}_${index}`, name: '', source: 'position', policy: 'buy_only',
    symbols: [], market: 'cn', targetPct: 0, batchAmount: null, currentAmount: null, sortOrder: index };
}

const reasons: Record<string, [string, string]> = {
  ledger_not_confirmed: ['请确认该范围的持仓和现金已完整录入', 'Confirm the complete holdings and cash ledger'],
  portfolio_accounts_missing: ['请先建立账户并录入资产', 'Create an account and record your assets'],
  manual_current_amount_missing: ['请填写当前余额，未知不能填 0', 'Enter the current balance; unknown is not zero'],
  position_price_missing: ['价格缺失，请更新行情', 'Missing quote; refresh prices'],
  position_price_stale: ['价格已过期，请更新行情', 'Stale quote; refresh prices'],
  close_reference: ['最近收盘参考价', 'Latest close reference'],
  fx_reference: ['日线汇率估算', 'Daily FX estimate'],
  position_fx_unreliable: ['汇率不可靠，请刷新汇率', 'Unreliable FX; refresh rates'],
  cash_fx_unreliable: ['现金换算汇率不可靠', 'Cash conversion is unreliable'],
  cash_budget_unavailable: ['可用现金待核实', 'Verify available cash'],
  cash_budget_limited: ['已按扣除预留后的剩余现金限制', 'Limited by cash after reserves'],
  cash_reserve_only: ['预留现金，不生成买卖指令', 'Cash reserve; no trade action'],
  below_target: ['低于目标，等待交易条件确认', 'Below target; verify entry conditions'],
  below_min_band: ['低于配置下限，等待交易条件确认', 'Below lower band; verify entry conditions'],
  above_target: ['超过目标，检查减仓条件', 'Above target; review reduction conditions'],
  inside_rebalance_band: ['在再平衡区间内', 'Inside rebalance band'],
  at_or_above_target: ['已达到目标', 'At or above target'],
  policy_hold_only: ['仅跟踪', 'Track only'],
  policy_exit_only: ['只减不增', 'Exit only'],
  current_amount_unavailable: ['当前金额待核实', 'Verify current value'],
};

export function AllocationPanel({ accounts, snapshot, costMethod }: {
  accounts: PortfolioAccountItem[];
  snapshot: PortfolioSnapshotResponse | null;
  costMethod: PortfolioCostMethod;
}) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [plans, setPlans] = useState<Omit<AllocationPlan, 'targets'>[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [status, setStatus] = useState<AllocationStatus | null>(null);
  const [draft, setDraft] = useState<AllocationPlanWrite | null>(null);
  const [editingId, setEditingId] = useState<number | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [realtime, setRealtime] = useState(false);
  const [group, setGroup] = useState<{ planId: number; keys: string[] }>({ planId: 0, keys: [] });
  const requestRef = useRef(0);
  const editRef = useRef(0);

  useEffect(() => {
    let active = true;
    portfolioApi.getAllocationPlans().then(({ plans: items }) => {
      if (!active) return;
      setPlans(items);
      setSelectedId((id) => items.some((plan) => plan.id === id) ? id : items[0]?.id ?? null);
    }).catch((err) => { if (active) setError(getParsedApiError(err).message); });
    return () => { active = false; };
  }, [refresh]);

  useEffect(() => {
    const request = ++requestRef.current;
    setStatus(null);
    if (!selectedId) { setLoading(false); return; }
    setLoading(true);
    portfolioApi.getAllocationStatus(selectedId, { costMethod, includeRealtime: realtime })
      .then((result) => {
        if (request === requestRef.current) { setStatus(result); setError(''); }
      })
      .catch((err) => { if (request === requestRef.current) setError(getParsedApiError(err).message); })
      .finally(() => { if (request === requestRef.current) setLoading(false); });
    return () => { requestRef.current += 1; };
  }, [selectedId, costMethod, snapshot, refresh, realtime]);

  const money = (value: number | null | undefined, currency = status?.baseCurrency ?? 'CNY') =>
    value == null ? (zh ? '待核实' : 'Unknown') : new Intl.NumberFormat(zh ? 'zh-CN' : 'en-US', {
      style: 'decimal', minimumFractionDigits: 2, maximumFractionDigits: 2,
    }).format(value) + ` ${currency}`;
  const reason = (value: string) => {
    const [code, ...details] = value.split(':');
    const label = reasons[code]?.[zh ? 0 : 1] ?? code;
    return details.length ? `${label} (${details.join(' · ')})` : label;
  };
  const groupedTargets = status?.planId === group.planId
    ? status.targets.filter((target) => group.keys.includes(target.key)) : [];
  const groupSum = (field: 'currentAmount' | 'targetAmount' | 'gapAmount' | 'fundedAmount') =>
    groupedTargets.some((target) => target[field] == null) ? null
      : groupedTargets.reduce((sum, target) => sum + (target[field] ?? 0), 0);
  const updateTarget = (index: number, patch: Partial<AllocationTarget>) => setDraft((current) => current && ({
    ...current, targets: current.targets.map((target, i) => i === index ? { ...target, ...patch } : target),
  }));
  const startCreate = () => {
    editRef.current += 1;
    setEditingId(undefined);
    setError('');
    setDraft({ name: '', baseCurrency: 'CNY', targetTotalValue: 1000000, accountId: null,
      ledgerComplete: false, cashReserveAmount: 0, includeInReports: false, targets: [blankTarget(0)] });
  };
  const startEdit = async () => {
    if (!selectedId) return;
    const id = selectedId;
    const request = ++editRef.current;
    try {
      const plan = await portfolioApi.getAllocationPlan(id);
      if (request === editRef.current) { setDraft(plan); setEditingId(id); setError(''); }
    } catch (err) { if (request === editRef.current) setError(getParsedApiError(err).message); }
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    if (Math.abs(draft.targets.reduce((sum, target) => sum + target.targetPct, 0) - 100) > 0.01) {
      setError(zh ? '目标占比合计必须为 100%。' : 'Target percentages must add up to 100%.');
      return;
    }
    setSaving(true);
    try {
      const saved = await portfolioApi.saveAllocationPlan(draft, editingId);
      setDraft(null); setSelectedId(saved.id); setError(''); setRefresh((value) => value + 1);
    } catch (err) { setError(getParsedApiError(err).message); }
    finally { setSaving(false); }
  };

  return <Card>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-base font-semibold text-foreground">{zh ? '目标配置' : 'Target allocation'}</h2>
        <p className="text-xs text-secondary mt-1">{zh ? '按计划绑定的账户范围计算，独立于上方账户筛选。' : 'Uses each plan’s saved account scope, independently of the filter above.'}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <select aria-label={zh ? '配置计划' : 'Allocation plan'} className={inputClass + ' !w-auto'} value={selectedId ?? ''}
          onChange={(event) => { editRef.current += 1; setDraft(null); setSelectedId(Number(event.target.value)); }} disabled={saving}>
          {!plans.length && <option value="">{zh ? '尚无计划' : 'No plans'}</option>}
          {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name}</option>)}
        </select>
        <button type="button" className="btn-secondary text-sm" onClick={startCreate} disabled={saving}>{zh ? '新建计划' : 'New plan'}</button>
        <button type="button" className="btn-secondary text-sm" onClick={() => void startEdit()} disabled={!selectedId || saving}>{zh ? '编辑计划' : 'Edit plan'}</button>
        <button type="button" className="btn-secondary text-sm" disabled={!selectedId || loading || saving}
          onClick={() => { setRealtime(true); setRefresh((value) => value + 1); }}>{zh ? '更新配置行情' : 'Refresh allocation quotes'}</button>
      </div>
    </div>
    {error && <InlineAlert variant="danger" message={error} className="mt-3" />}
    {draft && <form onSubmit={(event) => void save(event)} className="mt-4 space-y-4">
      <fieldset disabled={saving} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <label className="text-xs">{zh ? '计划名称' : 'Plan name'}<input required maxLength={96} className={inputClass} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label className="text-xs">{zh ? '计划资产总额' : 'Plan capital'}<input required type="number" min="0.01" step="0.01" className={inputClass} value={draft.targetTotalValue} onChange={(e) => setDraft({ ...draft, targetTotalValue: Number(e.target.value) })} /></label>
          <label className="text-xs">{zh ? '计价币种' : 'Currency'}<select className={inputClass} value={draft.baseCurrency} onChange={(e) => setDraft({ ...draft, baseCurrency: e.target.value })}>{['CNY', 'USD', 'HKD', 'JPY', 'KRW', 'TWD'].map((currency) => <option key={currency}>{currency}</option>)}</select></label>
          <label className="text-xs">{zh ? '账户范围' : 'Account scope'}<select className={inputClass} value={draft.accountId ?? ''} onChange={(e) => setDraft({ ...draft, accountId: e.target.value ? Number(e.target.value) : null, ledgerComplete: false })}>
            <option value="">{zh ? '全部活跃账户' : 'All active accounts'}</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </select></label>
          <label className="text-xs">{zh ? '额外现金预留（取它与现金目标的较大值）' : 'Cash reserve (at least the cash target)'}<input type="number" min="0" step="0.01" className={inputClass} value={draft.cashReserveAmount} onChange={(e) => setDraft({ ...draft, cashReserveAmount: Number(e.target.value) })} /></label>
        </div>
        <p className="text-xs text-secondary">{zh ? '金额均使用计划币种；多项加仓按下列顺序共用现金预算。手工余额留空表示未知。' : 'Amounts use plan currency. Additions share cash in the order below. Leave unknown manual balances empty.'}</p>
        {draft.targets.map((target, index) => <fieldset key={target.key} className="border border-border rounded-xl p-3 space-y-3">
          <legend className="text-xs px-1">{zh ? '资产' : 'Asset'} {index + 1}</legend>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <label className="text-xs">{zh ? '资产名称' : 'Asset name'}<input required className={inputClass} value={target.name} onChange={(e) => updateTarget(index, { name: e.target.value })} /></label>
            <label className="text-xs">{zh ? '金额来源' : 'Value source'}<select className={inputClass} value={target.source} onChange={(e) => updateTarget(index, { source: e.target.value as AllocationTarget['source'], symbols: [], market: null, currentAmount: null })}>
              <option value="position">{zh ? '持仓市值' : 'Positions'}</option><option value="cash">{zh ? '账户现金' : 'Cash'}</option><option value="manual">{zh ? '手工余额' : 'Manual balance'}</option>
            </select></label>
            <label className="text-xs">{zh ? '目标占比 %' : 'Target %'}<input required type="number" min="0" max="100" step="0.01" className={inputClass} value={target.targetPct} onChange={(e) => updateTarget(index, { targetPct: Number(e.target.value) })} /></label>
            <label className="text-xs">{zh ? '配置策略' : 'Policy'}<select className={inputClass} value={target.policy} onChange={(e) => updateTarget(index, { policy: e.target.value as AllocationTarget['policy'] })}>
              {(['buy_only', 'rebalance', 'hold_only', 'exit_only'] as const).map((policy, i) => <option key={policy} value={policy}>{zh ? ['只增不减', '区间再平衡', '仅跟踪', '只减不增'][i] : policy.replaceAll('_', ' ')}</option>)}
            </select></label>
            {target.source === 'position' && <>
              <label className="text-xs">{zh ? '证券代码（逗号分隔）' : 'Symbols (comma separated)'}<input required className={inputClass} value={target.symbols.join(',')} onChange={(e) => updateTarget(index, { symbols: e.target.value.split(/[,，\s]+/) })} /></label>
              <label className="text-xs">{zh ? '市场' : 'Market'}<select className={inputClass} value={target.market ?? ''} onChange={(e) => updateTarget(index, { market: (e.target.value || null) as AllocationTarget['market'] })}><option value="">{zh ? '不限' : 'Any'}</option>{['cn', 'hk', 'us', 'jp', 'kr', 'tw'].map((market) => <option key={market}>{market}</option>)}</select></label>
            </>}
            {target.source === 'manual' && <label className="text-xs">{zh ? '当前余额（未知留空）' : 'Current balance (blank if unknown)'}<input type="number" min="0" step="0.01" className={inputClass} value={target.currentAmount ?? ''} onChange={(e) => updateTarget(index, { currentAmount: e.target.value === '' ? null : Number(e.target.value) })} /></label>}
            <label className="text-xs">{zh ? '单批上限（留空以缺口为上限）' : 'Batch cap (blank: gap)'}<input type="number" min="0.01" step="0.01" className={inputClass} value={target.batchAmount ?? ''} onChange={(e) => updateTarget(index, { batchAmount: e.target.value === '' ? null : Number(e.target.value) })} /></label>
            <label className="text-xs">{zh ? '下限 %（可选）' : 'Lower band %'}<input type="number" min="0" max="100" step="0.01" className={inputClass} value={target.minPct ?? ''} onChange={(e) => updateTarget(index, { minPct: e.target.value === '' ? null : Number(e.target.value) })} /></label>
            <label className="text-xs">{zh ? '上限 %（可选）' : 'Upper band %'}<input type="number" min="0" max="100" step="0.01" className={inputClass} value={target.maxPct ?? ''} onChange={(e) => updateTarget(index, { maxPct: e.target.value === '' ? null : Number(e.target.value) })} /></label>
          </div>
          <button type="button" className="text-xs text-secondary" onClick={() => setDraft({ ...draft, targets: draft.targets.filter((_, i) => i !== index) })}>{zh ? '移除此资产' : 'Remove asset'}</button>
        </fieldset>)}
        <button type="button" className="btn-secondary text-sm" onClick={() => setDraft({ ...draft, targets: [...draft.targets, blankTarget(draft.targets.length)] })}>{zh ? '添加资产' : 'Add asset'}</button>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.ledgerComplete} onChange={(e) => setDraft({ ...draft, ledgerComplete: e.target.checked })} />{zh ? '我已完整录入所选范围的持仓、交易和现金余额' : 'I have recorded all holdings, trades and cash for this scope'}</label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.includeInReports} onChange={(e) => setDraft({ ...draft, includeInReports: e.target.checked })} />{zh ? '加入每日简报（金额会发送给现有报告接收人）' : 'Include in daily reports (balances go to existing report recipients)'}</label>
        <div className="flex gap-2"><button type="submit" className="btn-primary text-sm" disabled={!draft.targets.length}>{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存配置' : 'Save allocation')}</button><button type="button" className="btn-secondary text-sm" onClick={() => { editRef.current += 1; setDraft(null); }}>{zh ? '取消' : 'Cancel'}</button></div>
      </fieldset>
    </form>}
    {loading && <p className="text-sm text-secondary mt-4">{zh ? '正在计算配置…' : 'Evaluating allocation…'}</p>}
    {!selectedId && !draft && !error && <p className="text-sm text-secondary mt-4">{zh ? '新建计划，录入目标占比和手工资产余额后，即可跟踪配置缺口。' : 'Create a plan to track targets and allocation gaps.'}</p>}
    {status && !loading && <div className="mt-4 space-y-4">
      <p className="text-xs text-secondary">{status.asOf} · v{status.planVersion} · {zh ? '占比分母：计划资产' : 'Weight denominator: plan capital'} {money(status.targetTotalValue)} · {status.accountId == null ? (zh ? '全部活跃账户' : 'All active accounts') : accounts.find((a) => a.id === status.accountId)?.name}</p>
      {status.dataQuality === 'partial' && <InlineAlert variant="warning" message={zh ? '部分数据待核实，请先处理表格中的条件，再决定是否执行。' : 'Some data needs review. Resolve the conditions below before acting.'} />}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {[[zh ? '现金预留' : 'Cash reserve', status.cashReserveAmount], [zh ? '账面预算余额' : 'Ledger budget remaining', status.availableCash], [zh ? '合计账面配置上限' : 'Total ledger additions cap', status.totalRecommendedAdd], [zh ? '已核实现金上限' : 'Confirmed cash cap', status.confirmedCash]].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-border p-3"><p className="text-xs text-secondary">{label}</p><p className="mt-1 font-semibold tabular-nums">{money(value as number | null | undefined)}</p></div>)}
      </div>
      <p className="text-xs text-secondary">{zh ? '已核实现金按市场与原币分别限制；缺少当日确认时显示待核实，不代表可以买入。计划追加资金不计入现金。' : 'Confirmed cash is capped by market and native currency. Without current confirmation it is unknown, not permission to buy. Planned deposits are excluded.'}</p>
      {!!status.fundingAccounts?.some((account) => account.plannedDeposit != null) && <p className="text-xs text-secondary">
        {zh ? '尚未到账的计划追加：' : 'Planned deposits, not received: '}
        {status.fundingAccounts.filter((account) => account.plannedDeposit != null).map((account) => `#${account.accountId} ${money(account.plannedDeposit, account.currency)}${account.plannedDepositDate ? ` (${account.plannedDepositDate})` : ''}`).join(' · ')}
      </p>}
      <p className="text-xs text-secondary md:hidden">{zh ? '横向滑动表格可查看金额上限和等待条件。' : 'Scroll the table horizontally for caps and conditions.'}</p>
      <div className="overflow-x-auto"><table className="w-full text-sm min-w-[850px]">
        <thead><tr className="border-b border-border text-secondary">{(zh ? ['资产', '目标 / 当前占比', '当前金额', '目标缺口', '本批上限', '状态与等待条件'] : ['Asset', 'Target / current %', 'Current value', 'Gap', 'Batch cap', 'Status and conditions']).map((heading) => <th key={heading} className="text-left p-2 font-medium">{heading}</th>)}</tr></thead>
        <tbody>{status.targets.map((target) => <tr key={target.key} className="border-b border-border align-top">
          <td className="p-2 font-medium">{target.name}<div className="text-xs text-secondary">{target.symbols.join(' / ')}</div></td>
          <td className="p-2 tabular-nums">{target.targetPct}% / {target.currentPct == null ? '—' : `${target.currentPct.toFixed(2)}%`}</td>
          <td className="p-2 tabular-nums">{money(target.currentAmount)}</td><td className="p-2 tabular-nums">{money(target.gapAmount)}</td>
          <td className="p-2 tabular-nums"><div className="text-xs text-secondary">{zh ? '目标 / 批次：' : 'Target / batch: '}{money(target.allocationCap)}</div>
            <div>{zh ? '账面预算：' : 'Ledger budget: '}<span>{money(target.recommendedAmount)}</span></div>
            <div className="font-medium">{zh ? '现金覆盖：' : 'Cash-backed: '}{money(target.fundedAmount)}</div>
            {target.isEstimate && <div className="text-xs text-warning">{zh ? '估算参考，非实时指令' : 'Estimate, not a live instruction'}</div>}</td>
          <td className="p-2 max-w-xs"><span className={target.action === 'review' ? 'text-warning' : ''}>{zh ? { add: '有配置空间', reduce: '检查减仓', hold: '等待 / 持有', review: '先核实数据' }[target.action] : target.action}</span>
            <div className="text-xs text-secondary mt-1">{(target.limitations.length ? target.limitations : [target.reason]).map(reason).join('；')}</div>
            {!!target.referenceNotes?.length && <div className="text-xs text-secondary mt-1">{target.referenceNotes.map(reason).join('；')}</div>}</td>
        </tr>)}</tbody>
      </table></div>
      <details className="rounded-xl border border-border p-3 text-sm">
        <summary className="cursor-pointer">{zh ? '分组查看（仅汇总，不新增预算）' : 'Group view (summary only, no extra budget)'}</summary>
        <div className="flex flex-wrap gap-3 my-3">{status.targets.map((target) => <label className="flex items-center gap-1" key={target.key}>
          <input type="checkbox" checked={groupedTargets.includes(target)} onChange={(e) => setGroup({ planId: status.planId,
            keys: e.target.checked ? [...groupedTargets.map((t) => t.key), target.key] : groupedTargets.filter((t) => t.key !== target.key).map((t) => t.key) })} />
          {zh ? '汇总 ' : 'Include '}{target.name}</label>)}</div>
        {!!groupedTargets.length && <p data-testid="allocation-group-summary" className="tabular-nums">
          {zh ? '目标 ' : 'Target '}{money(groupSum('targetAmount'))} · {zh ? '当前 ' : 'Current '}{money(groupSum('currentAmount'))} · {zh ? '缺口 ' : 'Gap '}{money(groupSum('gapAmount'))} · {zh ? '现金覆盖合计 ' : 'Cash-backed sum '}{money(groupSum('fundedAmount'))}
        </p>}
        <p className="text-xs text-secondary mt-2">{zh ? '例如勾选美股与黄金，可查看已有目标的小计；不会另建独立预算或重复分配同一笔现金。' : 'Select assets such as US holdings and gold to subtotal existing targets. This does not create another plan or allocate cash again.'}</p>
      </details>
      {status.unassignedPositions.length > 0 && <p className="text-xs text-warning">{zh ? '未归类持仓：' : 'Unassigned positions: '}{status.unassignedPositions.map((position) => position.symbol).join(', ')}</p>}
      <p className="text-xs text-secondary">{zh ? '正缺口表示低配，负缺口表示超配。金额为配置上限；执行前需核验行情、估值、消息、费用和换汇可用性。减仓款到账前不计入可用现金。' : 'Positive gap: underweight; negative: overweight. Verify quotes, valuation, news, fees and FX availability before execution. Pending sales do not fund additions.'}</p>
    </div>}
  </Card>;
}
