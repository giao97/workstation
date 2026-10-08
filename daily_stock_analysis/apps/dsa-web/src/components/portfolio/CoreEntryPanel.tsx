import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { AllocationStatus } from '../../types/portfolio';

const labels: Record<string, [string, string]> = {
  candidate: ['回撤候选，待综合复核', 'Pullback candidate; review required'],
  wait: ['等待价格条件', 'Wait for price setup'],
  risk_review: ['先复核风险，不机械补仓', 'Review risk before averaging down'],
  data_required: ['日线数据不足，不代表市场不适合买', 'Daily data needed; not a bearish view'],
  calendar_unavailable: ['交易日历不可用', 'Trading calendar unavailable'],
  need_latest_60_sessions: ['需最近已完成的连续 60 个交易日日线', 'Need the latest 60 completed sessions'],
  invalid_close: ['日线价格异常', 'Invalid daily close'],
  source_missing_or_mixed: ['来源缺失或混用，需统一口径', 'Missing / mixed price sources'],
  large_move_or_deep_drawdown: ['异常跳变、单日急跌或深度回撤', 'Discontinuity, sharp fall or deep drawdown'],
  pullback_and_close_not_lower: ['回撤条件满足，最近收盘未再下跌', 'Pullback setup with a non-declining close'],
  wait_for_stabilization: ['已回撤，但最近收盘仍在下跌', 'Pullback present; close still declining'],
  no_pullback_setup: ['尚未满足本版回撤筛选条件', 'No setup under this research screen'],
  pullback_below_ma20: ['距 60 日收盘高点回撤 ≥3%，且不高于 MA20', 'At least 3% below 60-session closing high and at/below MA20'],
  near_60_session_low: ['接近 60 日收盘低点、回撤 ≥3%，且不高于 MA60', 'Near 60-session closing low, drawdown ≥3%, at/below MA60'],
  below_cost_context_only: ['低于账本成本（仅参考，不单独触发）', 'Below ledger cost (context only)'],
};

export function CoreEntryPanel({ status }: { status: AllocationStatus }) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const items = status.targets.flatMap(target => (target.coreEntries ?? []).map(entry => ({ target, entry })));
  if (!items.length) return null;
  const label = (code: string) => labels[code]?.[zh ? 0 : 1] ?? code;
  const metricNames = zh
    ? { close: '收盘价', ma20: 'MA20', ma60: 'MA60', low60: '60 日收盘低点', high60: '60 日收盘高点', drawdownPct: '距高点 %', aboveLowPct: '距低点 %', dailyChangePct: '单日 %', ledgerCost: '账本成本参考', versusCostPct: '相对成本 %' }
    : { close: 'Close', ma20: 'MA20', ma60: 'MA60', low60: '60-session closing low', high60: '60-session closing high', drawdownPct: 'From high %', aboveLowPct: 'Above low %', dailyChangePct: 'Daily %', ledgerCost: 'Ledger cost reference', versusCostPct: 'Versus cost %' };
  return <section className="rounded-xl border border-border p-3 space-y-3" aria-label={zh ? '长期择机分批' : 'Opportunity-based core accumulation'}>
    <h3 className="font-medium">{zh ? '长期择机分批 · QQQM / VOO' : 'Opportunity-based accumulation · QQQM / VOO'}</h3>
    <p className="text-xs text-secondary">{zh ? '不按固定日期买，不要求花完预算。近期低位不是历史最低价；低于成本不等于便宜。此处仅为日线参考，与做 T 的分钟线条件分开。' : 'No fixed purchase dates or spending requirement. Recent lows are not all-time lows; below cost is not fair value. Daily research is separate from intraday trading.'}</p>
    {items.map(({ target, entry }) => <article key={`${target.key}:${entry.symbol}`} className="border-t border-border pt-3 space-y-2">
      <p className="text-sm font-medium">{entry.symbol} · {label(entry.state)}</p>
      <p className="text-xs text-secondary">{[...entry.reasons, ...entry.checks].map(label).join('；')}</p>
      <p className="text-xs text-secondary">{zh ? '日线截至' : 'Daily through'} {entry.asOf ?? '—'} · {entry.sources.join(' / ') || (zh ? '来源待补' : 'Source missing')} · {entry.method}</p>
      {!!Object.keys(entry.metrics).length && <dl className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">{Object.entries(entry.metrics).map(([key, value]) => <div key={key}><dt className="text-secondary">{metricNames[key as keyof typeof metricNames] ?? key}</dt><dd className="tabular-nums">{value.toFixed(2)}</dd></div>)}</dl>}
      <p className="text-xs text-secondary">{entry.allocationReady
        ? (zh ? '配置层有现金覆盖额度；仍须复核长期判断、当日价格、费用及碎股规则，不是买入授权。' : 'Allocation has a cash-backed cap; thesis, live quote, fees and fractional rules still need review.')
        : (zh ? '目标、预算或现金条件尚不支持新增；价格候选不解除配置限制。' : 'Allocation or funding does not support additions; a price candidate does not override these gates.')}</p>
    </article>)}
    <p className="text-xs text-warning">{zh ? '试行筛选规则，未经回测；复权口径、估值和新闻尚未在此模块核验。出现新交易日收盘或重大消息后需重评；盘中须刷新报价，不自动下单，也不新增或重置预算。' : 'Unvalidated research screen; adjustment basis, valuation and news are not verified here. Reassess after a new close or material news; refresh quotes intraday. No orders or budget changes.'}</p>
  </section>;
}
