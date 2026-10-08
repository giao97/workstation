import { useEffect, useRef, useState } from 'react';
import { etfExposureApi, type CompositionPreview, type ExposureReport } from '../../api/etfExposure';
import { getParsedApiError } from '../../api/error';
import type { PortfolioAccountItem } from '../../types/portfolio';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card, InlineAlert } from '../common';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const labels: Record<string, [string, string]> = {
  eligible: ['日期符合检查规则，非实时', 'Date eligible, not realtime'], stale: ['成分过期，停止交集计算', 'Stale: comparison blocked'],
  future: ['未来日期不可用', 'Future date unavailable'], date_mismatch: ['成分日期不同，不混算', 'Composition dates differ'],
  stale_or_future: ['至少一份成分过期或日期异常', 'Stale or invalid composition date'],
  recorded_ledger: ['已记录账本，非券商同步', 'Recorded ledger, not broker sync'],
  no_recorded_holdings: ['未读取到已记录持仓，不代表实际空仓', 'No recorded holdings; not proof of an empty account'],
  profile_reference: ['投资档案代码参考，非正式账本', 'Profile symbols, not the formal ledger'],
  profile_stale: ['投资档案已过期，暂停关联', 'Stale profile; linkage paused'],
  profile_invalid: ['投资档案格式无效', 'Invalid profile'], profile_unavailable: ['投资档案读取失败', 'Profile unavailable'],
};
const label = (value: string, zh: boolean) => labels[value]?.[zh ? 0 : 1] ?? value;
const pct = (value: number) => `${value.toFixed(2)}%`;

export function EtfExposurePanel({ accounts, ledgerContext }: { accounts: PortfolioAccountItem[]; ledgerContext?: unknown }) {
  const { language } = useUiLanguage(); const zh = language === 'zh';
  const [account, setAccount] = useState('');
  const [revision, setRevision] = useState(0);
  const [response, setResponse] = useState<{ account: string; ledgerContext: unknown; revision: number; data: ExposureReport | null; error: string } | null>(null);
  const current = response?.account === account && response?.ledgerContext === ledgerContext && response?.revision === revision;
  const report = current ? response.data : null;
  const error = current ? response.error : '';
  const loading = !current;
  useEffect(() => {
    let active = true;
    etfExposureApi.report(account ? Number(account) : undefined)
      .then((data) => { if (active) setResponse({ account, ledgerContext, revision, data, error: '' }); })
      .catch((e) => { if (active) setResponse({ account, ledgerContext, revision, data: null, error: getParsedApiError(e).message }); });
    return () => { active = false; };
  }, [account, ledgerContext, revision]);
  return <Card className="space-y-4">
    <h2 className="text-lg font-semibold">{zh ? 'ETF 成分穿透 · 重叠检查' : 'ETF look-through · overlap review'}</h2>
    <p className="text-sm text-secondary-text">{zh ? '先检查来源与覆盖，再看共同股票。这里的百分比以各基金净资产为分母，不是你的组合仓位；不输出买卖指令。' : 'Check sources and coverage first. Percentages use each fund’s NAV, not your portfolio value. No trade instructions.'}</p>
    <div className="flex flex-wrap gap-3 items-end">
      <label className="text-xs flex-1">{zh ? '穿透持仓范围' : 'Exposure scope'}<select className={inputClass} value={account} onChange={(e) => setAccount(e.target.value)}>
        <option value="">{zh ? '全部已记录持仓 / 已配置档案' : 'All recorded holdings / configured profile'}</option>
        {accounts.filter((a) => a.isActive).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select></label>
      <button disabled={loading} className="btn-secondary" onClick={() => setRevision((r) => r + 1)}>{zh ? '重新检查本地资料' : 'Review local evidence'}</button>
    </div>
    {loading && <p role="status">{zh ? '读取本地成分与持仓范围…' : 'Reading local compositions and holding scope…'}</p>}
    {error && <InlineAlert variant="danger" message={error} />}
    {report && <>
      <div className="rounded-xl border border-border p-3 space-y-2 text-sm">
        <p>{label(report.holding_context.status, zh)}{report.holding_context.profile_date ? ` · ${report.holding_context.profile_date}` : ''}</p>
        <p>{zh ? '检查范围：' : 'Scope: '}{report.holdings.map((h) => `${h.symbol} (${h.market})`).join(' / ') || '—'}</p>
        <p>{zh ? '已关联成分资料：' : 'Matched composition evidence: '}{report.funds.length} / {report.holdings.length} {zh ? '只持仓产品（非金额覆盖率）' : 'held instruments (not value coverage)'}</p>
        <p className="text-warning">{zh ? '组合金额/行业占比：尚未计算。未接入同一时点估值、完整公司归属及行业映射。' : 'Portfolio value/sector exposure: not calculated. Coherent valuation, issuer and sector mappings are not integrated.'}</p>
        <p className="text-xs">{zh ? `成分日期容许落后 ${report.freshness_policy_days} 个自然日，这是本地检查规则，不保证期间未调仓。检查时间：` : `Composition age limit: ${report.freshness_policy_days} calendar days, not a guarantee of unchanged holdings. Checked: `}{report.generated_at}</p>
      </div>
      {report.unclassified_holdings.length > 0 && <InlineAlert variant="warning" message={`${zh ? '以下持仓类型或成分未确认，不视为零风险：' : 'Unclassified holdings or missing compositions, not zero risk: '}${report.unclassified_holdings.map((h) => h.symbol).join(' / ')}`} />}
      {!report.funds.length && <p className="text-sm">{zh ? '暂无与持仓匹配的成分快照。请录入核对过的发行人成分资料；本页不会用内置示例或模型猜测权重。' : 'No compositions match these holdings. Import reviewed issuer evidence; no sample or model-invented weights are substituted.'}</p>}
      {report.funds.map((fund) => <details key={fund.id} className="rounded-lg border border-border p-3 text-sm">
        <summary className="cursor-pointer">{fund.fund_symbol} · {fund.holdings_as_of} · {label(fund.coverage.status, zh)} · {zh ? '披露权重' : 'Disclosed'} {pct(fund.coverage.disclosed_pct)}</summary>
        <p className="mt-2">{zh ? '股票 / 基金（未继续穿透）/ 现金 / 其他 / 未披露：' : 'Equity / nested funds / cash / other / undisclosed: '}{[fund.coverage.equity_pct, fund.coverage.nested_fund_pct, fund.coverage.cash_pct, fund.coverage.other_pct, fund.coverage.undisclosed_pct].map(pct).join(' / ')}</p>
        <a className="text-primary underline break-all" href={fund.source_url} target="_blank" rel="noopener noreferrer">{fund.source_name}</a>
        <p className="text-xs break-all">{zh ? '来源发布时间 / 系统留存时间：' : 'Published / retained: '}{fund.source_published_at ?? (zh ? '未知，不推算' : 'Unknown, not inferred')} / {fund.recorded_at}</p>
        <p className="text-xs break-all">#{fund.id} · {fund.row_count} {zh ? '行' : 'rows'} · SHA256 {fund.content_hash}</p>
      </details>)}
      {!!report.pairs.length && <div className="space-y-3"><h3 className="font-semibold">{zh ? '基金两两交集（不可相加）' : 'Fund-pair overlap (not additive)'}</h3>
        <p className="text-xs">{zh ? '已披露股票交集 = 共同上市证券的 min(基金 A 权重, 基金 B 权重) 之和。仅精确匹配市场和代码；0% 仅表示已披露部分未匹配，不证明充分分散。' : 'Observed equity overlap = sum of min(A weight, B weight) for exact market/symbol matches. Zero means no disclosed match, not full diversification.'}</p>
        {report.pairs.map((pair) => <details key={`${pair.left_snapshot_id}-${pair.right_snapshot_id}`} className="border border-border rounded-lg p-3 text-sm">
          <summary className="cursor-pointer">{pair.left} × {pair.right} · {pair.observed_overlap_pct == null ? label(pair.status, zh) : `${zh ? '已披露交集' : 'Observed overlap'} ${pct(pair.observed_overlap_pct)} · ${pair.shared_count} ${zh ? '只' : 'listings'}`}</summary>
          {pair.shared.length > 0 && <div className="overflow-x-auto mt-2"><table className="w-full text-xs"><thead><tr><th>{zh ? '上市证券' : 'Listing'}</th><th>{pair.left}</th><th>{pair.right}</th><th>{zh ? '交集贡献' : 'Contribution'}</th></tr></thead>
            <tbody>{pair.shared.map((s) => <tr key={`${s.market}:${s.symbol}`}><td className="py-2">{s.market}:{s.symbol}</td><td>{pct(s.left_weight_pct)}</td><td>{pct(s.right_weight_pct)}</td><td>{pct(s.overlap_pct)}</td></tr>)}</tbody></table></div>}
          {pair.shared_count != null && pair.shared_count > 20 && <p>{zh ? '仅展示前 20 项；总交集包含全部共同股票。' : 'Top 20 shown; total uses all shared equities.'}</p>}
        </details>)}
      </div>}
      {!!report.held_constituent_matches.length && <div className="text-sm"><h3 className="font-semibold">{zh ? '持仓代码同时出现在基金股票成分中' : 'Held symbols also present in equity constituents'}</h3>
        {report.held_constituent_matches.map((m) => <p key={`${m.snapshot_id}:${m.market}:${m.symbol}`}>{m.symbol} ({m.market}) → {m.fund}: {pct(m.fund_weight_pct)} {zh ? '基金内权重，不是组合总暴露' : 'within fund, not total portfolio exposure'}</p>)}
      </div>}
      <p className="text-xs text-secondary-text">{zh ? '人工核对不等于系统独立认证。当前只做一层股票成分匹配；不自动合并 ADR、本地股、不同股类，不计算嵌套基金、衍生品和因子风险。库中资料不代表你已持有；过期或异日数据不计算交集。' : 'Manual review is not independent verification. One equity layer only: no ADR/share-class merging, nested funds, derivatives or factor risk. Library membership is not a holding. Stale or different-date evidence blocks comparison.'}</p>
    </>}
    <CompositionImport zh={zh} onSaved={() => setRevision((r) => r + 1)} />
  </Card>;
}

function CompositionImport({ zh, onSaved }: { zh: boolean; onSaved: () => void }) {
  const [document, setDocument] = useState('');
  const [preview, setPreview] = useState<{ result: CompositionPreview; input: Record<string, unknown> } | null>(null);
  const [reviewed, setReviewed] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [saved, setSaved] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const run = async (commit: boolean) => {
    setBusy(true); setError(''); setSaved(false);
    try {
      if (commit) {
        if (!preview || !reviewed) return;
        await etfExposureApi.save(preview.input);
        if (active.current) { setPreview(null); setReviewed(false); setSaved(true); onSaved(); }
      } else {
        setPreview(null); setReviewed(false);
        const input: unknown = JSON.parse(document);
        if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error(zh ? '请输入 JSON 对象' : 'Enter a JSON object');
        const result = await etfExposureApi.preview(input as Record<string, unknown>);
        if (active.current) setPreview({ result, input: input as Record<string, unknown> });
      }
    } catch (e) { if (active.current) setError(getParsedApiError(e).message); }
    finally { if (active.current) setBusy(false); }
  };
  return <details className="border-t border-border pt-3"><summary className="cursor-pointer text-sm">{zh ? '录入已核对成分资料（研究库，不是买入）' : 'Import reviewed composition (research only)'}</summary>
    <p className="text-xs my-3">{zh ? '本版需整理发行人资料为 JSON，不自动抓取网址。字段：fund_symbol、fund_market(us)、holdings_as_of、source_url、source_name、source_published_at(含时区；不明为 null)、methodology(long_only_nav_weight_pct)、constituents。每行需 market、symbol、name、kind(equity/fund/cash/other)、weight_pct(1 表示 1%，不是 100%)。仅支持非杠杆、非做空的净资产权重。成分日期必须明确；留存时间不冒充发布时间，不能用于事前回测。' : 'Manual issuer evidence as JSON; URLs are not fetched. Fields: fund_symbol, fund_market(us), holdings_as_of, source_url, source_name, source_published_at(zoned or null), methodology(long_only_nav_weight_pct), constituents. Each row: market, symbol, name, kind(equity/fund/cash/other), weight_pct(1 means 1%). Only unlevered, long-only NAV weights. Composition date required; retention is not publication and cannot support point-in-time backtests.'}</p>
    <fieldset disabled={busy} className="space-y-3">
      <label className="block text-xs">{zh ? '成分 JSON' : 'Composition JSON'}<textarea rows={6} maxLength={600000} className={inputClass} value={document} onChange={(e) => { setDocument(e.target.value); setPreview(null); setReviewed(false); setSaved(false); }} /></label>
      <button disabled={!document.trim()} className="btn-secondary" onClick={() => void run(false)}>{zh ? '校验预览（不保存）' : 'Validate preview (no save)'}</button>
      {preview && <div className="space-y-2 text-sm"><p>{zh ? '披露权重：' : 'Disclosed: '}{pct(preview.result.coverage.disclosed_pct)} · {zh ? '未披露：' : 'Undisclosed: '}{pct(preview.result.coverage.undisclosed_pct)} · {label(preview.result.coverage.status, zh)}</p>
        <label className="block"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> {zh ? '我已核对来源、日期、代码和净资产百分比单位；非杠杆/做空产品' : 'I reviewed source, dates, identities and NAV percentage units; unlevered long-only product'}</label>
        <button disabled={!reviewed} className="btn-primary" onClick={() => void run(true)}>{zh ? '确认保存成分快照' : 'Save composition snapshot'}</button>
      </div>}
    </fieldset>
    {busy && <p role="status">{zh ? '处理本地资料…' : 'Processing local evidence…'}</p>}
    {error && <InlineAlert variant="danger" message={error} />}
    {saved && <p role="status">{zh ? '成分快照已保存；未修改持仓、现金或交易。' : 'Composition saved; holdings, cash and trades unchanged.'}</p>}
  </details>;
}
