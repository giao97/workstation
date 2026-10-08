import { useEffect, useRef, useState } from 'react';
import { paperObservationsApi, type MinuteRules, type PaperAssumptions, type PaperEvaluation, type PaperExperiment } from '../../api/paperObservations';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { InlineAlert } from '../common';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const reasons: Record<string, [string, string]> = {
  awaiting_completed_sessions: ['等待后续完整交易日', 'Waiting for complete forward sessions'],
  calendar_unavailable: ['交易日历不可用', 'Exchange calendar unavailable'],
  missing_session_bar: ['缺少交易日日线，不跳过缺口', 'Missing a session; gaps are not skipped'],
  corporate_action_unsupported: ['包含分红或拆股，暂不核算', 'Distributions/splits require separate accounting'],
  daily_provider_unavailable: ['日线提供方暂不可用', 'Daily provider unavailable'],
  daily_provenance_missing: ['价格口径或来源不足', 'Insufficient price provenance'],
  currency_or_market_unverified: ['币种或市场未核实', 'Currency/market unverified'],
  invalid_daily_bar: ['日线数据不合格', 'Invalid daily data'],
  protected_shares: ['触及模拟底仓保护', 'Protected simulated shares'],
  entry_cash_insufficient: ['模拟开仓现金不足', 'Insufficient simulated entry cash'],
  exit_cash_insufficient: ['模拟回补资金不足，不追加本金', 'Insufficient exit cash; no added capital'],
  entry_liquidity_insufficient: ['入场流动性不足', 'Entry liquidity insufficient'],
  exit_liquidity_insufficient: ['退出流动性不足', 'Exit liquidity insufficient'],
  non_directional_action: ['观察类建议，不模拟交易', 'Non-directional signal: no trade simulated'],
  signal_inactive_before_entry: ['入场前建议已失效', 'Signal inactive before entry'],
  observation_window_too_old: ['观察记录超过一年，停止新取数', 'Observation over one year old'],
  clock_precedes_capture: ['系统时间早于归档时间', 'Clock precedes capture'],
  unsupported_symbol: ['代码格式暂不支持', 'Unsupported symbol'],
  policy_version_unsupported: ['冻结的规则版本不受当前引擎支持', 'Frozen policy version unsupported'],
  minute_awaiting_expiry: ['等待冻结截止时间及15分钟数据缓冲；非实时信号', 'Waiting for frozen expiry plus 15-minute buffer; not a live signal'],
  minute_history_window_expired: ['超过6天取数窗口；不补造历史分钟', 'Past the six-day retrieval window; no fabricated minute history'],
  minute_provider_unavailable: ['分钟行情提供方暂不可用', 'Minute provider unavailable'],
  minute_provenance_missing: ['分钟价格口径或来源不足', 'Insufficient minute provenance'],
  minute_gap_or_time_invalid: ['分钟缺失、顺序或时区不合格，暂停核算', 'Missing minutes or invalid ordering/timezone; replay blocked'],
  invalid_minute_bar: ['分钟数据不合格', 'Invalid minute data'],
  minute_no_trigger: ['有效期内未确认入场条件', 'No entry confirmation before expiry'],
  minute_no_next_bar: ['条件在最后一分钟确认，已无后续成交窗口', 'Last-minute confirmation; no next execution window'],
  minute_exit_not_filled: ['截止时未模拟恢复股数', 'Original shares not restored at expiry'],
  minute_invalidated: ['触及冻结失效价，停止撮合且不追补', 'Frozen invalidation touched; stop replay without chasing'],
  minute_ambiguous_range: ['同分钟触及回补/退出和失效区间，不认定成功往返', 'Exit and invalidation touched in one minute; no successful cycle inferred'],
  minute_price_bound: ['下一分钟价格加滑点后超出冻结边界', 'Next-minute price plus slippage violates frozen bound'],
  minute_liquidity_insufficient: ['前一分钟量不足或本分钟成交量无法支持模拟数量', 'Prior-minute capacity or current trade volume is insufficient'],
  minute_expiry_out_of_range: ['截止时间必须晚于归档时刻，且在未来7天内', 'Expiry must be after capture and within seven days'],
  minute_expiry_outside_session: ['截止时间须在常规交易时段内，并留出至少两个完整观察分钟', 'Expiry must be inside a regular session with at least two observation minutes'],
  minute_exceeds_signal_expiry: ['模拟截止时间不能超过源建议有效期', 'Replay expiry cannot extend the source signal validity'],
  minute_requires_active_directional_signal: ['分钟回放仅接受有效的买入/加仓/减仓/卖出建议', 'Minute replay requires an active buy/add/reduce/sell signal'],
  minute_price_order_invalid: ['价格顺序不符合该建议方向，请检查入场、退出及失效价', 'Check entry, exit and invalidation price ordering for this action'],
  minute_request_invalid: ['请填写有效截止时间', 'Enter a valid expiry time'],
  paper_request_key_conflict: ['请求键已用于另一组参数，请重新打开表单后提交', 'Request key already used for different parameters; reopen the form'],
};
const reasonText = (key: string, zh: boolean) => reasons[key]?.[zh ? 0 : 1] ?? key;
const states: Record<string, [string, string]> = {
  pending: ['待观察', 'Pending'], blocked: ['数据不足', 'Blocked'], no_fill: ['未模拟成交', 'No simulated fill'],
  open: ['未恢复原股数', 'Shares not restored'], completed: ['模拟闭合', 'Simulated round trip'],
};
const fields = [
  ['quantity', '模拟机动股数', 'Simulated trade shares', '1'],
  ['baseline_shares', '模拟期初股数', 'Simulated initial shares', '0'],
  ['protected_shares', '模拟保护股数', 'Simulated protected shares', '0'],
  ['cash_usd', '模拟已结算现金 USD', 'Simulated settled cash USD', '0'],
  ['buy_fee_usd', '整笔买入总费用 USD（假设）', 'Total buy fees USD (assumed)', '0'],
  ['sell_fee_usd', '整笔卖出总费用 USD（假设）', 'Total sell fees USD (assumed)', '0'],
  ['slippage_bps', '每边不利滑点 bps（假设）', 'Adverse slippage bps per side (assumed)', '0'],
] as const;

export function PaperObservationPanel({ signalId, market }: { signalId: number; market: string }) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [expanded, setExpanded] = useState(false);
  return <section className="rounded-xl border border-border p-4 space-y-3">
    <button type="button" className="btn-secondary text-sm" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {zh ? '独立模拟观察（不交易）' : 'Independent paper observations (no trading)'}
    </button>
    <p className="text-xs text-secondary">{zh ? '冻结当前建议与假设。可选日线固定窗口或分钟条件事后回放；两者均不是真实成交或实时操作提醒。' : 'Freeze the current signal and assumptions. Choose daily windows or retrospective minute-rule replay; neither represents real fills or live trading alerts.'}</p>
    {expanded && (market === 'us' ? <Experiments key={signalId} signalId={signalId} zh={zh} /> :
      <p className="text-sm">{zh ? '首版仅支持美元计价的美股/ETF。' : 'This version supports USD US stocks/ETFs only.'}</p>)}
  </section>;
}

function Experiments({ signalId, zh }: { signalId: number; zh: boolean }) {
  const [items, setItems] = useState<PaperExperiment[]>([]);
  const [evaluation, setEvaluation] = useState<PaperEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState('daily');
  const retry = useRef<{ payload: string; key: string } | null>(null);
  useEffect(() => {
    let active = true;
    paperObservationsApi.list(signalId).then(({ items }) => {
      if (active) setItems((current) => [...current, ...items.filter((item) => !current.some((existing) => existing.id === item.id))]);
    })
      .catch((e) => { if (active) setError(reasonText(getParsedApiError(e).message, zh)); });
    return () => { active = false; };
  }, [signalId, zh]);
  return <div className="space-y-3">
    <InlineAlert variant="warning" message={zh ? '每个窗口都是独立假设资金，不能把结果相加当组合收益。未对接真实账户；费用、滑点及 T+1 结算是假设，不是致富账户规则确认。' : 'Each window uses independent hypothetical capital; do not sum them as portfolio returns. No real-account connection; fees, slippage and T+1 settlement are assumptions, not verified broker rules.'} />
    <form onSubmit={async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const assumptions = Object.fromEntries(fields.map(([name]) => [name, Number(form.get(name))])) as Omit<PaperAssumptions, 'fee_note'>;
      const payload: PaperAssumptions = { ...assumptions, fee_note: String(form.get('fee_note')) };
      const expiry = new Date(String(form.get('expires_at')));
      if (mode === 'minute' && !Number.isFinite(expiry.getTime())) {
        setError(reasonText('minute_request_invalid', zh)); return;
      }
      const minuteRules: MinuteRules | undefined = mode === 'minute' ? {
        entry_price: Number(form.get('entry_price')), exit_price: Number(form.get('exit_price')),
        invalidation_price: Number(form.get('invalidation_price')),
        expires_at: expiry.toISOString(),
      } : undefined;
      const serialized = JSON.stringify({ payload, minuteRules });
      if (retry.current?.payload !== serialized) retry.current = { payload: serialized, key: crypto.randomUUID() };
      setBusy(true); setError('');
      try {
        const item = minuteRules ? await paperObservationsApi.capture(signalId, retry.current.key, payload, minuteRules)
          : await paperObservationsApi.capture(signalId, retry.current.key, payload);
        setItems((old) => [item, ...old.filter((other) => other.id !== item.id)]);
        retry.current = null; // Only uncertain retries reuse a key; explicit new captures get a new timestamp.
      } catch (e) { setError(reasonText(getParsedApiError(e).message, zh)); }
      finally { setBusy(false); }
    }}>
      <fieldset disabled={busy} className="space-y-3">
        <label className="text-xs block">{zh ? '模拟规则' : 'Paper policy'}<select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="daily">{zh ? '日线固定窗口（原版）' : 'Daily fixed windows (original)'}</option>
          <option value="minute">{zh ? '单时段分钟条件回放' : 'Single-session minute-rule replay'}</option>
        </select></label>
        {mode === 'minute' && <div className="space-y-3 rounded-lg border border-border p-3">
          <p className="text-xs">{zh ? '买入：失效价 < 入场上限 < 退出下限；卖出：回补上限 < 入场下限 < 失效价。以分钟收盘确认，下一分钟开盘加不利滑点仍满足边界才模拟成交。仅一轮，到期不强制平仓。' : 'Buy: invalidation < entry ceiling < exit floor. Sell: buyback ceiling < entry floor < invalidation. Confirm at minute close, then try the next open with adverse slippage and bounds. One cycle; no forced close at expiry.'}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {([['entry_price', '入场边界 USD', 'Entry bound USD'], ['exit_price', '回补/退出边界 USD', 'Buyback/exit bound USD'], ['invalidation_price', '失效价 USD', 'Invalidation USD']] as const).map(([name, cn, en]) =>
              <label key={name} className="text-xs">{zh ? cn : en}<input className={inputClass} name={name} type="number" min="0.000001" max="1000000" step="any" required /></label>)}
            <label className="text-xs">{zh ? '截止时间（本机时区）' : 'Expiry (device timezone)'}<input className={inputClass} type="datetime-local" name="expires_at" required /></label>
          </div>
          <p className="text-xs text-secondary">{Intl.DateTimeFormat().resolvedOptions().timeZone} · {zh ? '截止时间须在未来7天内的一个美股常规时段，且不超过源建议有效期。归档后开始，只在截止后15分钟检查；请在6天取数窗口内回放。' : 'Expiry must be within a regular US session in the next seven days and within the source signal validity. Start after capture; check 15 minutes after expiry, within the six-day retrieval window.'}</p>
        </div>}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {fields.map(([name, cn, en, min]) => <label key={name} className="text-xs">{zh ? cn : en}
            <input className={inputClass} name={name} type="number" required min={min} step={name.includes('shares') || name === 'quantity' ? '1' : 'any'} />
          </label>)}
        </div>
        <label className="text-xs block">{zh ? '费用假设依据（不填账号或密钥）' : 'Fee assumption note (no account IDs or secrets)'}<input className={inputClass} name="fee_note" required maxLength={240} /></label>
        <label className="text-xs flex items-start gap-2"><input type="checkbox" required />{zh ? '我确认这些是独立模拟参数，不是录入真实持仓或成交。' : 'These are independent paper assumptions, not real holdings or fills.'}</label>
        <button type="submit" className="btn-primary text-sm">{zh ? '冻结建议与假设' : 'Freeze signal and assumptions'}</button>
      </fieldset>
    </form>
    {error && <InlineAlert variant="danger" message={error} />}
    <p className="text-xs text-secondary">{mode === 'daily'
      ? (zh ? '日线规则：归档日之后首个交易日开盘操作，第 1/3/5/10 个交易日收盘反向恢复股数；不执行原建议的价格触发、止损、止盈。' : 'Daily rule: first session open after capture day, reverse at session 1/3/5/10 close; original trigger/stop/target levels are not executed.')
      : (zh ? '分钟规则：必须有连续完整的1分钟数据。触及失效价停止撮合；缺分钟或价格口径不明时不算盈利。无盘口排队和部分成交模型，不保证可成交。' : 'Minute rule: contiguous complete 1-minute bars required. Invalidation stops replay; missing data/basis blocks profit calculations. No order-book queue or partial-fill model; no fill guarantee.')}</p>
    {!items.length && <p className="text-xs">{zh ? '尚无模拟归档；不会自动补造历史样本。' : 'No paper archive yet; historical samples are not invented.'}</p>}
    {items.map((item) => <div className="rounded-lg border border-border p-3 text-xs space-y-2" key={item.id}>
      <p>#{item.id} · {item.snapshot.stock_code} · {item.snapshot.action} · {new Date(item.captured_at).toLocaleString()}</p>
      <p>{item.snapshot.paper_policy_version ?? 'paper-window-v1'}</p>
      {item.snapshot.minute_rules && <p>{zh ? '冻结：入场 / 回补退出 / 失效' : 'Frozen: entry / exit / invalidation'}: {item.snapshot.minute_rules.entry_price} / {item.snapshot.minute_rules.exit_price} / {item.snapshot.minute_rules.invalidation_price} USD<br />{zh ? '截止（UTC）' : 'Expiry (UTC)'}: {item.snapshot.minute_rules.expires_at}</p>}
      <p>{zh ? '模拟股数 / 期初 / 保护' : 'Trade / initial / protected shares'}: {item.assumptions.quantity} / {item.assumptions.baseline_shares} / {item.assumptions.protected_shares}</p>
      <p>{zh ? '现金 / 买费 / 卖费（USD）' : 'Cash / buy fee / sell fee (USD)'}: {item.assumptions.cash_usd} / {item.assumptions.buy_fee_usd} / {item.assumptions.sell_fee_usd} · {item.assumptions.slippage_bps} bps</p>
      <p className="break-words">{item.assumptions.fee_note}</p>
      {item.snapshot.reason && <details><summary>{zh ? '归档时的建议理由' : 'Reason at capture'}</summary><p className="break-words whitespace-pre-wrap">{item.snapshot.reason}</p></details>}
      <details><summary>{zh ? '冻结校验值' : 'Snapshot hash'}</summary><p className="break-all">{item.snapshot_hash}</p></details>
      <button type="button" className="btn-secondary text-xs" disabled={busy} onClick={async () => {
        setBusy(true); setError(''); setEvaluation(null);
        try { setEvaluation(await paperObservationsApi.evaluate(item.id)); }
        catch (e) { setError(reasonText(getParsedApiError(e).message, zh)); }
        finally { setBusy(false); }
      }}>{zh ? '检查后续观察' : 'Check forward observations'}</button>
    </div>)}
    {evaluation && <div className="space-y-2">
      <p className="text-xs">#{evaluation.experiment.id} · {evaluation.engine_version} · {new Date(evaluation.observed_at).toLocaleString()}</p>
      {evaluation.items.map((row) => <div key={row.horizon} className="border border-border rounded-lg p-3 text-sm space-y-1">
        <p>{row.horizon === 0 ? (zh ? '单时段分钟回放' : 'Single-session minute replay') : `${row.horizon}${zh ? ' 个交易日' : ' sessions'}`} · {states[row.status]?.[zh ? 0 : 1] ?? row.status}</p>
        {row.reason && <p className="text-xs">{reasons[row.reason]?.[zh ? 0 : 1] ?? row.reason}</p>}
        <p>{zh ? '相对不操作（模拟）' : 'Versus no action (simulated)'}: {row.relative_hold_pnl == null ? '—' : `${row.relative_hold_pnl.toFixed(2)} USD`}</p>
        {row.opportunity_loss != null && <p>{zh ? '落后不操作' : 'Shortfall versus no action'}: {row.opportunity_loss.toFixed(2)} USD</p>}
        {row.economic_cost_improvement_per_share != null && <p>{zh ? '恢复股数后每股经济降本（负值为变差）' : 'Economic improvement per baseline share (negative = worse)'}: {row.economic_cost_improvement_per_share.toFixed(4)} USD</p>}
        {row.status === 'open' && <p className="text-xs">{zh ? '未闭合，仅参考收盘估值差，不能宣称成功降本。' : 'Open position: marked difference only, not successful cost reduction.'}</p>}
        {row.source && <p className="text-xs break-all">{row.source} · {row.entry_date} → {row.end_date} · {row.fetched_at}</p>}
        {row.horizon === 0 && <details className="text-xs"><summary>{zh ? '模拟过程（非真实成交）' : 'Simulated events (not real fills)'}</summary>
          {row.fills?.map((fill, i) => <p className="break-all" key={i}>{fill.timestamp} · {fill.side} {fill.quantity} × {fill.price} USD · {zh ? '费用' : 'Fee'} {fill.fee} USD<br />{zh ? '确认分钟起点' : 'Confirmation bar start'}: {fill.confirmation_bar}</p>)}
          {row.events?.map((event, i) => <p className="break-all" key={i}>{event.timestamp} · {reasons[event.reason ?? event.kind]?.[zh ? 0 : 1] ?? event.kind}</p>)}
        </details>}
      </div>)}
    </div>}
  </div>;
}
