import { useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';
import type { PerformanceReview, PortfolioAccountItem, TradingContribution } from '../../types/portfolio';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const labels: Record<string, [string, string]> = {
  restored: ['已恢复期初股数', 'Initial share count restored'],
  under_baseline: ['净减持，尚未恢复股数', 'Below initial share count'],
  over_baseline: ['净增持，尚未恢复股数', 'Above initial share count'],
  no_activity: ['期间无交易', 'No period trades'],
  unsupported: ['公司行动待专门核算', 'Corporate-action review needed'],
  performance_ledger_unconfirmed: ['期初持仓和期间全部流水尚未确认完整', 'Initial holdings and full period ledger are unconfirmed'],
  performance_costs_unverified: ['费用未全部核实，净收益未知', 'Unverified costs: net contribution is unknown'],
  performance_execution_time_unknown: ['部分成交时间未知，不推断准确日内顺序', 'Some execution times are unknown; no precise intraday sequence is inferred'],
  performance_corporate_action_unsupported: ['区间含分红或拆股，暂不计算持有对照及降本', 'Dividends/splits in this period block the benchmark and cost improvement'],
  performance_endpoint_unavailable: ['缺少合格期末估值，未闭合收益对照留空', 'No usable endpoint price; open-position comparison is unavailable'],
  realtime_not_requested: ['未请求实时参考价', 'Live reference not requested'],
  market_valuation_unsupported: ['该市场估值暂不支持', 'Market valuation is unsupported'],
  valuation_currency_mismatch: ['账本币种与该市场报价币种不一致', 'Ledger and market quote currencies differ'],
  historical_unadjusted_endpoint_unavailable: ['历史未复权期末价尚未核实', 'Historical unadjusted endpoint is unverified'],
  quote_unavailable: ['未取得报价', 'No quote available'],
  quote_stale_or_unverifiable: ['报价过期或来源/时间不可核验', 'Stale or unverifiable quote'],
  intraday_execution_time_unknown: ['当日成交时间未知，无法确认报价在成交之后', 'Unknown intraday execution time prevents endpoint alignment'],
  quote_precedes_execution: ['报价早于已录入成交', 'Quote precedes a recorded fill'],
  fresh_timestamped_quote: ['带时间戳的参考估值，非可成交保证', 'Timestamped reference valuation, not a fill guarantee'],
};
const label = (key: string, zh: boolean) => labels[key]?.[zh ? 0 : 1] ?? key;
const money = (value: number | null, currency: string, zh: boolean, digits = 2) => value == null
  ? (zh ? '待核实 / 不适用' : 'Unknown / not applicable')
  : `${value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} ${currency}`;

export function PerformancePanel({ accounts, ledgerContext }: {
  accounts: PortfolioAccountItem[]; ledgerContext?: object | null;
}) {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [expanded, setExpanded] = useState(false);
  const [accountId, setAccountId] = useState<number | null>(null);
  const account = accounts.find((a) => a.id === accountId) ?? accounts[0];
  return <Card>
    <button className="btn-secondary text-sm" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {zh ? '波段收益与持续持有对照' : 'Trading contribution versus holding'}
    </button>
    <p className="text-xs text-secondary mt-2">{zh ? '只读复盘，不下单、不修改成本。卖出回笼现金不等于利润；日常加仓也不会自动归为做T。' : 'Read-only review: no orders or cost edits. Sale proceeds are not profit; regular additions are not automatically classified as trading cycles.'}</p>
    {expanded && <div className="mt-3 space-y-3">
      <label className="text-xs">{zh ? '复盘账户' : 'Review account'}<select className={inputClass} value={account?.id ?? ''} onChange={(e) => setAccountId(Number(e.target.value))}>
        {!accounts.length && <option value="">{zh ? '请先创建账户' : 'Create an account first'}</option>}
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.baseCurrency}</option>)}
      </select></label>
      {account && <Review key={account.id} account={account} context={ledgerContext} zh={zh} />}
    </div>}
  </Card>;
}

function Review({ account, context, zh }: { account: PortfolioAccountItem; context?: object | null; zh: boolean }) {
  const [result, setResult] = useState<{ data: PerformanceReview; context?: object | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const report = result?.context === context ? result?.data : null;
  return <div className="space-y-3">
    <form onChange={() => setResult(null)} onSubmit={async (e) => {
      e.preventDefault();
      const f = new FormData(e.currentTarget);
      setBusy(true); setError(''); setResult(null);
      try {
        const data = await portfolioApi.reviewPerformance(account.id, {
          startDate: String(f.get('start')), endDate: String(f.get('end')),
          symbols: String(f.get('symbols')).split(/[,，\s]+/).filter(Boolean),
          ledgerConfirmed: f.get('confirmed') === 'on', includeRealtime: f.get('realtime') === 'on',
        });
        setResult({ data, context });
      } catch (e) { setError(getParsedApiError(e).message); }
      finally { setBusy(false); }
    }}>
      <fieldset disabled={busy} className="space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="text-xs">{zh ? '开始日期（含）' : 'Start date (inclusive)'}<input name="start" type="date" required className={inputClass} /></label>
          <label className="text-xs">{zh ? '结束日期（含）' : 'End date (inclusive)'}<input name="end" type="date" required className={inputClass} /></label>
          <label className="text-xs">{zh ? '标的（留空按期间活动）' : 'Symbols (blank: period activity)'}<input name="symbols" className={inputClass} placeholder="EUV, HAL" /></label>
        </div>
        <p className="text-xs text-secondary">{zh ? '按交易所日期计算，纳入该区间全部成交，不挑选盈利交易。基准为期初股数及相同现金不操作；期初零股时，基准是保留现金，不是买入后持有。' : 'Exchange dates; all period trades are included, not just winners. Benchmark: keep initial shares and identical cash unchanged. With zero initial shares, the benchmark is cash, not buying and holding.'}</p>
        <label className="text-xs flex items-start gap-2"><input type="checkbox" name="confirmed" />{zh ? '已核对期初持仓、期间全部成交和分红拆股记录完整' : 'I have reconciled initial holdings, all period trades and corporate actions'}</label>
        <label className="text-xs flex items-start gap-2"><input type="checkbox" name="realtime" />{zh ? '尝试读取未闭合仓位参考价（仅期末为交易所今日，非交易信号）' : 'Try a live endpoint for open positions (only when ending today; not a signal)'}</label>
        <button type="submit" className="btn-primary text-sm">{busy ? (zh ? '核算中…' : 'Calculating…') : (zh ? '只读核算' : 'Calculate without writes')}</button>
      </fieldset>
    </form>
    {error && <InlineAlert variant="danger" message={error} />}
    {result && !report && <InlineAlert variant="warning" message={zh ? '持仓页面已刷新，请重新核算，旧结果不再展示。' : 'The portfolio has refreshed. Recalculate; the previous result is hidden.'} />}
    {report && <div className="space-y-3">
      <p className="text-xs text-secondary">{report.startDate} — {report.endDate} · {report.timezone} · {zh ? '生成时间' : 'Generated'} {report.generatedAt}</p>
      {!report.items.length && <p className="text-sm">{zh ? '区间内没有可核算的活动，不生成虚构往返。' : 'No recorded period activity; no cycles are invented.'}</p>}
      {report.items.map((item) => <Contribution key={`${item.symbol}-${item.market}-${item.currency}`} item={item} zh={zh} />)}
      {report.totalsByCurrency.map((total) => <div className="rounded-lg border border-border p-3 text-sm" key={total.currency}>
        <h3 className="font-semibold">{zh ? '本次范围合计（非账户总收益）' : 'Selected-scope total (not account return)'} · {total.currency}</h3>
        <p>{zh ? '相对不操作' : 'Versus no trading'}: {money(total.relativeHoldPnl, total.currency, zh)}{total.containsMarkedEstimate ? (zh ? '（含估值差）' : ' (includes marks)') : ''}</p>
        <p className="text-xs text-secondary">{zh ? '已可比较标的' : 'Comparable items'} {total.comparableCount} / {total.itemCount}；{zh ? '仅已核实闭合部分' : 'Verified closed subset only'} ({total.closedVerifiedCount}): {money(total.verifiedClosedNetPnl, total.currency, zh)}</p>
      </div>)}
      <p className="text-xs text-secondary">{zh ? '不等同于券商已实现盈亏、账户收益率或年化收益；不计现金利息及个人所得税，不假设未来平仓费。真实成交价已包含成交滑点，不重复扣一笔假设滑点。股数减少不代表应当追高回补。' : 'Not broker tax-lot P&L, account return or annualised return. Cash interest, income tax and hypothetical future closing fees are excluded. Actual fills already reflect slippage. A share shortfall is not an instruction to chase a repurchase.'}</p>
      <details className="text-xs"><summary className="cursor-pointer">{zh ? '核算版本与证据指纹' : 'Method and evidence fingerprints'}</summary>
        <p>{report.methodologyVersion}</p><p className="break-all">{zh ? '账本' : 'Ledger'}: {report.ledgerFingerprint}</p><p className="break-all">{zh ? '本次证据' : 'Evidence'}: {report.evidenceHash}</p>
      </details>
    </div>}
  </div>;
}

function Contribution({ item: i, zh }: { item: TradingContribution; zh: boolean }) {
  const metrics: Array<[string, number | null, number?]> = [
    [zh ? '买卖毛现金差（不是利润）' : 'Gross cash flow (not profit)', i.grossCashFlow],
    [zh ? '已记录费用及税费' : 'Recorded fees and taxes', i.recordedCosts],
    [zh ? '恢复股数后净价差收益' : 'Closed net trading contribution', i.closedNetPnl],
    [zh ? '相对不操作的差额' : 'Difference versus no trading', i.relativeHoldPnl],
    [zh ? '每股经济回本价改善' : 'Economic break-even improvement/share', i.economicCostImprovementPerShare, 6],
  ];
  return <div className="rounded-xl border border-border p-3 space-y-3">
    <h3 className="font-semibold text-sm">{i.symbol} · {i.currency} · {label(i.status, zh)}</h3>
    <p className="text-xs">{zh ? '期初 / 期末股数' : 'Initial / ending shares'}: {i.baselineQuantity} / {i.endingQuantity} · {i.baselineKind === 'unchanged_cash' ? (zh ? '保留现金基准，无原底仓降本' : 'Cash benchmark; no original holding cost to lower') : (zh ? '保持期初股数基准' : 'Unchanged initial shares benchmark')}</p>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-sm">
      {metrics.map(([title, value, digits]) => <div key={title}><p className="text-xs text-secondary">{title}</p><p>{money(value, i.currency, zh, digits)}</p></div>)}
    </div>
    {i.comparisonKind === 'marked_estimate' && <p className="text-xs text-warning">{zh ? '包含未闭合仓位的参考估值差，不是已兑现利润，也未扣未来回补/平仓费。' : 'Includes an open-position reference mark, not realised profit; future closing costs are not deducted.'}</p>}
    {!!i.unverifiedFeeTradeIds.length && <p className="text-xs text-warning">{zh ? '费用待核实流水' : 'Unverified-cost trades'}: {i.unverifiedFeeTradeIds.join(', ')}</p>}
    {i.limitations.map((reason) => <p className="text-xs text-warning" key={reason}>{label(reason, zh)}</p>)}
    {i.valuation && <p className="text-xs text-secondary break-words">{zh ? '估值依据' : 'Valuation'}: {i.valuation.price ?? '—'} · {i.valuation.provider ?? '—'} · {i.valuation.timestamp ?? '—'} · {label(i.valuation.reason, zh)}</p>}
    <details><summary className="text-xs cursor-pointer">{zh ? '本区间全部成交依据' : 'All period execution evidence'} ({i.tradeCount})</summary>
      <div className="mt-2 space-y-2 text-xs">
        {i.trades.map((trade) => <p key={trade.id} className="break-words">#{trade.id} · {trade.executedAt ?? trade.tradeDate} · {trade.side === 'buy' ? (zh ? '买入' : 'Buy') : (zh ? '卖出' : 'Sell')} {trade.quantity} @ {trade.price} · {zh ? '费用/税费' : 'Fees/taxes'} {trade.fee} / {trade.tax} · {trade.feeStatus === 'confirmed' ? (zh ? '已核实' : 'Confirmed') : (zh ? '未核实' : 'Unverified')}</p>)}
      </div>
    </details>
  </div>;
}
