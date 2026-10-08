import { useEffect, useRef, useState } from 'react';
import { Newspaper, RefreshCw } from 'lucide-react';
import { marketEventsApi, NewsJobFailed, type NewsJob, type BriefSummary, type EventBrief, type EventMarket, type MarketEvent, type NewsSource, type SourceTemplate, type Verification } from '../api/marketEvents';
import { getParsedApiError } from '../api/error';
import { AppPage, Card, InlineAlert, PageHeader } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';

const inputClass = 'input-surface w-full rounded-lg border px-3 py-2 text-sm';
const labels: Record<string, string> = {
  today: '今日发布', carryover: '隔夜 / 前日延续', date_only: '只有日期，时点待核实', time_unknown: '发布时间待核实',
  pending: '排队中', processing: '任务开始', collecting: '采集新闻', selecting: '筛选并冻结证据', interpreting: '生成条件式解读', archiving: '保存快照', archived: '已归档（不代表解读全部完成）',
  model_call_failed: '模型调用失败', model_timeout: '模型调用超时', model_empty: '模型返回空内容',
  model_contract_invalid: '模型输出格式不合规', model_evidence_invalid: '引用或持仓越界，解读被拒绝', model_omitted_events: '模型遗漏部分事件',
  no_material: '未取得可留档材料', filtered_out: '已有材料，但未通过本期筛选',
  reported: '来源报道，未独立核验', unverified: '待核实', confirmed: '人工已核实', disputed: '存在争议', retracted: '已撤回 / 证伪',
  primary_link: '官方链接（不等于内容已核验）', available: '已取得', partial: '覆盖不完整', insufficient: '证据不足',
  provided_or_cached: '已有 / 手工材料，非实时扫描', model_unavailable: '未配置可用模型', model_failed_or_invalid: '模型失败或证据校验未通过',
  model_failed: '模型未返回结果', partial_analysis: '部分事件未完成解读', not_requested: '未请求 AI 解读',
  blocked_by_verification: '核验状态阻止继续解读', recorded_ledger: '已记录账本', no_recorded_holdings: '未读取到已记录持仓（不代表空仓）',
  profile_reference: '投资档案参考（仅代码，非交易账本）', profile_stale: '投资档案超过 7 天，已暂停关联',
  profile_invalid: '投资档案格式或日期异常，已暂停关联', profile_unavailable: '投资档案无法读取，已暂停关联',
  unavailable: '读取失败', ok: '成功', failed: '失败', cached: '读取缓存', empty: '无可用条目', unconfigured: '未配置 / 未启用',
  provided: '本次研报已采集材料', bounded: '受采集上限限制', old: '超过新闻窗口', future_publication: '发布时间在未来',
  macro: '宏观', geopolitics: '地缘 / 商品', technology: '科技', property: '房地产', company: '公司事件',
  upcoming_event: '未来已排期，尚未发生', unmatched_topic: '未命中财经主题规则', unmatched_market: '未命中市场相关性规则',
  holding_mention: '文本命中持仓代码（关联待核实）', explicit_market: '涉及研究市场', global_transmission: '跨市场影响线索', source_market: '资讯源市场标签', global_scope: '全球范围',
};
const statusLabel = (value: string, zh: boolean) => zh ? labels[value] ?? value : value === 'holding_mention' ? 'Symbol text match (identity unverified)' : value.replaceAll('_', ' ');
function Link({ url, children }: { url: string; children: React.ReactNode }) {
  return /^https?:\/\//i.test(url) ? <a className="text-primary underline break-all" href={url} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
}
function stamp(value: string | null, zh: boolean) {
  if (!value) return zh ? '未知' : 'Unknown';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `${date.toLocaleString(zh ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', hour12: false })} BJT`;
}

export default function MarketEventsPage() {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const [market, setMarket] = useState<EventMarket>('cn');
  return <AppPage><PageHeader eyebrow="NEWS RESEARCH" title={zh ? '今日市场事件' : 'Market events'}
    description={zh ? '先看证据，再看影响。新闻事实与 AI 条件式推演分开，研究不等于买卖信号。' : 'Evidence first. Source claims and AI hypotheses are separate; research is not a trading signal.'} />
    <label className="block my-4 text-sm">{zh ? '研究市场' : 'Market'}<select className={inputClass} value={market} onChange={(e) => setMarket(e.target.value as EventMarket)}>
      {(['cn', 'hk', 'us', 'global'] as const).map((m, i) => <option key={m} value={m}>{(zh ? ['A 股', '港股', '美股', '全球'] : ['China A-shares', 'Hong Kong', 'US', 'Global'])[i]}</option>)}
    </select></label>
    <Workspace key={`${market}-${language}`} market={market} language={language} />
  </AppPage>;
}

function Workspace({ market, language }: { market: EventMarket; language: 'zh' | 'en' }) {
  const zh = language === 'zh';
  const [history, setHistory] = useState<BriefSummary[]>([]);
  const [brief, setBrief] = useState<EventBrief | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(false);
  const [search, setSearch] = useState(true);
  const [scanSectors, setScanSectors] = useState(true);
  const [analyze, setAnalyze] = useState(true);
  const [manual, setManual] = useState({ title: '', summary: '', url: '', published_at: '', event_at: '' });
  const active = useRef(true);
  const sequence = useRef(0);
  const retry = useRef<{ input: string; key: string } | null>(null);
  const controller = useRef<AbortController | null>(null);
  const storageKey = `dsa.news.pending.${market}.${language}`;
  const [pendingKey, setPendingKey] = useState<string | null>(() => {
    try { return sessionStorage.getItem(storageKey); } catch { return null; }
  });
  const [stage, setStage] = useState('pending');
  const remember = (key: string | null) => {
    setPendingKey(key);
    // Storage may be disabled; in-page polling must still work.
    try { if (key) sessionStorage.setItem(storageKey, key); else sessionStorage.removeItem(storageKey); } catch { /* in-memory state remains available */ }
  };
  useEffect(() => {
    active.current = true;
    const seq = ++sequence.current;
    marketEventsApi.list(market).then(async (data) => {
      if (!active.current || seq !== sequence.current) return;
      setHistory(data.items);
      if (data.items[0]) {
        const first = await marketEventsApi.get(data.items[0].id);
        if (active.current && seq === sequence.current) setBrief(first);
      }
    }).catch((e) => { if (active.current && seq === sequence.current) setError(getParsedApiError(e).message); })
      .finally(() => { if (active.current && seq === sequence.current) setLoading(false); });
    return () => { active.current = false; controller.current?.abort(); };
  }, [market]);
  const generate = async (mode: 'new' | 'retry' | 'recover' = 'new') => {
    if (mode === 'retry' && !brief) return;
    setBusy(true); setError(''); const seq = ++sequence.current;
    controller.current?.abort(); controller.current = new AbortController(); setStage('pending');
    const input = { market, language, refresh_sources: refresh, search_news: search, analyze, scan_sectors: scanSectors,
      manual_items: manual.title.trim() ? [manual] : [] };
    const serialized = JSON.stringify(mode === 'retry' ? { parent: brief?.id } : input);
    if (retry.current?.input !== serialized) retry.current = { input: serialized, key: crypto.randomUUID() };
    const key = mode === 'recover' ? pendingKey : retry.current.key;
    if (!key) { setBusy(false); return; }
    remember(key);
    const update = (job: NewsJob) => { if (active.current && seq === sequence.current) setStage(job.stage); };
    try {
      const result = mode === 'recover' ? await marketEventsApi.waitForJob(key, update, controller.current.signal)
        : mode === 'retry' ? await marketEventsApi.retryAnalysis(brief!.id, key, update, controller.current.signal)
        : await marketEventsApi.generate({ ...input, request_key: key }, update, controller.current.signal);
      if (!active.current || seq !== sequence.current) return;
      setBrief(result); retry.current = null; remember(null);
      setHistory((items) => [result, ...items.filter((item) => item.id !== result.id)]);
    } catch (e) { if (active.current && seq === sequence.current) {
      if (e instanceof NewsJobFailed) {
        retry.current = null; remember(null);
        setError(zh ? '本次任务失败，未确认完成归档。可人工重新发起；不会自动重复调用模型。' : 'Task failed; archival was not confirmed. Retry explicitly; no automatic model retry.');
      } else if (e instanceof Error && e.message === 'market_event_job_unknown') {
        setError(zh ? '未找到任务或已归档结果，可能是服务重启或任务记录过期；请先查看历史，再决定是否重新生成。不会自动重试。' : 'Task/archive not found, possibly after a restart or expiry. Check history before explicitly regenerating. No automatic retry.');
      } else setError(`${getParsedApiError(e).message} ${zh ? '连接中断不代表服务端已取消；请先检查任务状态，避免重复生成。' : 'A disconnected request does not cancel server work. Check task status before generating again.'}`);
    } }
    finally { if (active.current && seq === sequence.current) { setBusy(false); setLoading(false); } }
  };
  const select = async (id: number) => {
    const seq = ++sequence.current; setLoading(true); setBrief(null); setError('');
    try { const result = await marketEventsApi.get(id); if (active.current && seq === sequence.current) setBrief(result); }
    catch (e) { if (active.current && seq === sequence.current) setError(getParsedApiError(e).message); }
    finally { if (active.current && seq === sequence.current) setLoading(false); }
  };
  return <div className="space-y-4">
    <Card><fieldset disabled={busy} className="space-y-3">
      <div className="flex flex-wrap gap-4 text-sm">
        <label><input type="checkbox" checked={search} onChange={(e) => setSearch(e.target.checked)} /> {zh ? '搜索当期新闻' : 'Search recent news'}</label>
        <label><input type="checkbox" checked={scanSectors} disabled={!search} onChange={(e) => setScanSectors(e.target.checked)} /> {zh ? `跨行业与热点扫描（另加 ${['cn', 'hk'].includes(market) ? 5 : 3} 组检索，可能计费）` : `Sector / theme scan (${['cn', 'hk'].includes(market) ? 5 : 3} extra searches; may incur charges)`}</label>
        <label><input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} /> {zh ? '刷新已启用资讯源' : 'Refresh enabled feeds'}</label>
        <label><input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} /> {zh ? '生成 AI 条件式解读' : 'AI conditional interpretation'}</label>
      </div>
      <p className="text-xs text-secondary-text">{zh ? '点击后才访问所选外部来源及已配置模型，可能产生调用费用。不会自动启用源、创建定时任务或下单；每期最多精选 8 个事件。' : 'External sources and configured models are called only on generation; charges may apply. No automatic feed enabling, schedules or orders. Up to eight selected events.'}</p>
      <details><summary className="text-sm cursor-pointer">{zh ? '补充一条快讯 / 截图文字（默认待核实）' : 'Add a news claim / transcribed screenshot (unverified)'}</summary>
        <div className="grid gap-3 mt-3 md:grid-cols-2">
          {(['title', 'url', 'published_at', 'summary', 'event_at'] as const).map((field, i) => <label key={field} className="text-xs">{(zh ? ['标题', '原文链接（可空）', '发布时间，含时区；不明留空', '原文摘要', '事件预定 / 发生时间，含时区（可空）'] : ['Title', 'Source URL (optional)', 'Publication time with timezone, or blank', 'Source excerpt', 'Scheduled / occurrence time with timezone (optional)'])[i]}
            {field === 'summary' ? <textarea className={inputClass} maxLength={2000} value={manual[field]} onChange={(e) => setManual({ ...manual, [field]: e.target.value })} />
              : <input className={inputClass} maxLength={field === 'title' ? 300 : field === 'url' ? 2000 : 100} value={manual[field]} placeholder={field === 'published_at' ? '2026-09-29T18:00:00+08:00' : ''} onChange={(e) => setManual({ ...manual, [field]: e.target.value })} />}
          </label>)}
        </div>
      </details>
      <button className="btn-primary inline-flex items-center gap-2" onClick={() => void generate()}><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />{busy ? (zh ? '正在收集并归档…' : 'Collecting and archiving…') : (zh ? '生成今日简报' : 'Generate today’s brief')}</button>
      {busy && <p role="status" className="text-xs">{statusLabel(stage, zh)} · {zh ? '阶段不是时间完成百分比。完成前仍显示上一次快照；切换市场不会取消服务端任务。' : 'Stages are not elapsed-time percentages. The previous snapshot stays visible; switching market does not cancel server work.'}</p>}
    </fieldset></Card>
    {pendingKey && !busy && <button className="btn-secondary" onClick={() => void generate('recover')}>{zh ? '检查上次任务状态（不重新生成）' : 'Check previous task (no regeneration)'}</button>}
    <SourceSettings zh={zh} />
    {error && <InlineAlert variant="danger" message={error} />}
    {!!history.length && <label className="block text-sm">{zh ? '历史快照（生成时间）' : 'Archived snapshots (capture time)'}<select disabled={busy || loading} className={inputClass} value={brief?.id ?? ''} onChange={(e) => void select(Number(e.target.value))}>
      {!brief && <option value="">{zh ? '加载中' : 'Loading'}</option>}{history.map((h) => <option key={h.id} value={h.id}>#{h.id} · {stamp(h.captured_at, zh)} · {h.language}{h.parent_brief_id ? (zh ? ' · 补充旧证据解读' : ' · old-evidence retry') : ''}</option>)}
    </select></label>}
    {loading && <p role="status">{zh ? '读取历史快照…' : 'Loading snapshots…'}</p>}
    {!loading && !brief && <Card><Newspaper className="h-6 w-6 mb-2" /><p>{zh ? '尚未生成事件简报。先配置新闻搜索或启用资讯源，也可粘贴一条消息开始核验。' : 'No event brief yet. Configure search or enable a feed, or paste a claim for review.'}</p></Card>}
    {brief && <>
      <Card><h2 className="font-semibold">{zh ? '本期覆盖与限制' : 'Coverage and limitations'} · {statusLabel(brief.coverage.status, zh)}</h2>
        <p className="text-xs mt-2">{stamp(brief.captured_at, zh)} · {zh ? '今日分组时区' : 'Day boundary'}: {brief.timezone} · {brief.events.length} / {brief.coverage.candidate_count} {zh ? '候选事件' : 'candidates'}</p>
        <p className="text-xs mt-2">{zh ? '持仓关联口径' : 'Holding basis'}: {statusLabel(brief.holding_status, zh)} · {brief.holdings.map((h) => `${h.symbol} (${h.market})`).join(' / ') || '—'}</p>
        {brief.holding_context?.profile_date && <p className="text-xs mt-2">{zh ? '档案版本日期（非成交或估值日期）' : 'Profile version date (not a trade or valuation date)'}: {brief.holding_context.profile_date}</p>}
        <p className="text-xs mt-2">{zh ? '模型解读状态' : 'Model interpretation'}: {statusLabel(brief.coverage.analysis_status, zh)}</p>
        {brief.parent_brief_id && <p className="text-xs text-warning mt-2">{zh ? '本次只补解读，没有刷新新闻或持仓；原简报' : 'Interpretation only; news and holdings not refreshed. Parent'} #{brief.parent_brief_id} · {stamp(brief.analysis_retried_at ?? null, zh)}</p>}
        {brief.coverage.analysis_failure && <p className="text-xs text-warning mt-2">{zh ? '解读缺口原因：' : 'Interpretation gap: '}{statusLabel(brief.coverage.analysis_failure, zh)}</p>}
        {brief.coverage.empty_reason && <p className="text-xs text-warning mt-2">{statusLabel(brief.coverage.empty_reason, zh)}</p>}
        {brief.events.some((e) => !e.analysis && !['disputed', 'retracted'].includes((brief.verification_history ?? []).filter((v) => v.event_key === e.event_key).at(-1)?.status ?? e.verification)) && <div className="mt-3">
          <button disabled={busy} className="btn-secondary text-sm" onClick={() => void generate('retry')}>{zh ? '仅重试缺失解读（可能计费）' : 'Retry missing interpretations only (may incur charges)'}</button>
          <p className="text-xs mt-1">{zh ? '沿用当时证据与持仓代码，不刷新来源，不覆盖成功结果；另存新快照。' : 'Reuse frozen evidence and holding symbols, keep successful results, and save a new snapshot without refreshing sources.'}</p>
        </div>}
        <p className="text-xs text-secondary-text mt-2">{zh ? '以账本为先；无账本账户时，仅可使用显式配置的投资档案。只向模型传持仓代码和市场，不传数量、金额、成本或档案原文，不自动同步券商。未核验实时行情、NAV、成分权重；不提供买卖价格和金额。排序是阅读优先级，不是盈利概率。' : 'Ledger first; an explicitly configured profile is used only when no ledger accounts exist. Only symbols and markets go to the model, never quantities, balances, costs or profile text. No broker sync, live quote, NAV or constituent verification, or trade instructions. Ranking is reading priority, not return probability.'}</p>
        <details className="text-xs mt-3"><summary>{zh ? '来源状态与排除项' : 'Source health and exclusions'}</summary>
          <ul className="mt-2 space-y-1">{brief.coverage.sources.map((s, i) => <li key={i}>{s.source}: {statusLabel(s.status, zh)}{s.query ? ` · ${s.query}` : ''}{s.truncated ? (zh ? '（条目已截断）' : ' (truncated)') : ''}</li>)}</ul>
          <p>{Object.entries(brief.coverage.excluded).map(([key, count]) => `${statusLabel(key, zh)}: ${count}`).join(' · ')}</p>
        </details>
      </Card>
      {!!brief.sector_radar?.length && <Card><h2 className="font-semibold">{zh ? '跨行业机会 · 证据观察池' : 'Cross-sector opportunities · evidence watch'}</h2>
        <p className="text-xs text-secondary mt-2">{zh ? '新快照覆盖筛选前候选池，旧快照仅含选中材料；不是全市场实时监控，也不是持仓或买入信号。需再验证收入/订单、估值、量价与失效条件；未覆盖不等于没有机会。' : 'New snapshots include the pre-selection candidate pool; legacy snapshots contain selected evidence only. Not live whole-market monitoring, holdings or buy signals. Verify fundamentals, valuation, price/volume and invalidation; gaps do not mean no opportunities.'}</p>
        <div className="grid gap-3 mt-3 md:grid-cols-3">{brief.sector_radar.map((row) => {
          const currentEligible = row.eligible_event_keys.filter((key) => !['disputed', 'retracted', 'unverified'].includes(
            (brief.verification_history ?? []).filter((v) => v.event_key === key).at(-1)?.status ?? 'reported'));
          return <div className="border border-border rounded-lg p-3 text-sm" key={row.sector}>
            <h3>{zh ? row.label_zh : row.label_en}</h3><p className="text-xs text-secondary mt-1">{currentEligible.length ? (zh ? '有新闻线索，待核验交易条件' : 'News leads; trading conditions unverified') : row.event_keys.length ? (zh ? '先核验消息与时点' : 'Verify claims and timing first') : (zh ? '本期选中材料未覆盖' : 'Not covered in selected evidence')}</p>
            {row.event_keys.map((key) => {
              const item = (brief.candidate_events ?? brief.events).find((event) => event.event_key === key);
              return <p className="text-xs mt-2" key={key}><Link url={item?.evidence[0]?.url ?? ''}>{item?.title}</Link>
                {!brief.events.some((event) => event.event_key === key) && <span> · {zh ? '未入选正文' : 'Not selected for body'}</span>}</p>;
            })}
          </div>;
        })}</div>
      </Card>}
      {brief.coverage_audit && <Card><h2 className="font-semibold">{zh ? '覆盖复盘 · 不把事后发现当提前判断' : 'Coverage audit · no hindsight credit'}</h2>
        <p className="text-xs mt-2">{zh ? '同市场当日首份原始快照基线：' : 'First original same-market snapshot today: '}
          {brief.coverage_audit.baseline_id ? `#${brief.coverage_audit.baseline_id} · ${stamp(brief.coverage_audit.baseline_at, zh)}` : (zh ? '无可比基线（旧快照可能未保存候选池）' : 'No comparable baseline (legacy pool may be absent)')}</p>
        <p className="text-xs text-secondary-text mt-2">{zh ? '只比较新闻覆盖，不证明盘前可买、买点触发或错失盈利；基线不一定是盘前报告。历史快照不被后续消息重写。' : 'Compares news coverage, not premarket tradability, triggers or missed profit. The baseline is not necessarily premarket. Later news never rewrites archived snapshots.'}</p>
        <ul className="text-sm mt-3 space-y-1">{brief.coverage_audit.rows.map((row) => {
          const states: Record<string, string> = { no_baseline: '无可比基线', not_observed_now: '本期未取得线索',
            previously_selected: '此前已入选新闻（非买入推荐）', previously_collected_not_selected: '此前收集到但未入选', newly_observed: '本次新发现，不能倒推此前可买' };
          return <li key={row.sector}>{zh ? row.label_zh : row.label_en}：{zh ? states[row.state] ?? row.state : row.state.replaceAll('_', ' ')}</li>;
        })}</ul>
      </Card>}
      {!brief.events.length && <InlineAlert variant="warning" message={zh ? '暂无足够证据，不代表今天没有重大消息。请检查来源和搜索配置。' : 'Insufficient evidence does not mean there are no material events. Check feeds and search configuration.'} />}
      {brief.events.map((event) => <EventCard key={`${brief.id}-${event.event_key}`} event={event} brief={brief} zh={zh}
        onVerified={(review) => setBrief((current) => current?.id === brief.id ? { ...current, verification_history: [...(current.verification_history ?? []), review] } : current)} />)}
    </>}
  </div>;
}

function EventCard({ event, brief, zh, onVerified }: { event: MarketEvent; brief: EventBrief; zh: boolean; onVerified: (v: Verification) => void }) {
  const reviews = (brief.verification_history ?? []).filter((v) => v.event_key === event.event_key);
  const current = reviews.at(-1)?.status ?? event.verification;
  const blocked = current === 'retracted' || current === 'disputed';
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const analysis = event.analysis;
  return <Card className="overflow-hidden"><div className="flex flex-wrap gap-2 text-xs text-secondary-text mb-2">
    <span>{statusLabel(current, zh)}</span><span>· {statusLabel(event.time_bucket, zh)}</span><span>· {event.topics.map((t) => statusLabel(t, zh)).join(' / ')}</span>
    {event.market_relevance && <span>· {statusLabel(event.market_relevance, zh)}</span>}
  </div><h2 className="font-semibold text-lg break-words">{event.title}</h2>
    {blocked && <InlineAlert variant="warning" message={zh ? '此事件后续存在争议或已撤回，旧解读不再作为当前判断依据。' : 'This event is disputed or retracted. The old interpretation is not current guidance.'} />}
    <div className="mt-3 space-y-3">{event.evidence.map((ev) => <div key={ev.evidence_id} className="rounded-xl border border-border p-3 text-sm">
      <p><Link url={ev.url}>{ev.source} · {zh ? '查看来源' : 'Source'}</Link> · {statusLabel(ev.source_tier, zh)}</p>
      <p className="text-xs text-secondary-text mt-1">{zh ? '发布' : 'Published'}: {stamp(ev.published_at, zh)} · {zh ? '事件发生' : 'Occurred'}: {stamp(ev.event_at, zh)}</p>
      <p className="text-xs text-secondary-text">{zh ? '系统首次留存' : 'First retained'}: {stamp(ev.first_seen_at, zh)}</p>
      <p className="mt-2 whitespace-pre-wrap break-words">{ev.summary || (zh ? '仅有标题，须查看原文，证据有限。' : 'Headline only; read the original source.')}</p>
    </div>)}</div>
    {analysis && !blocked ? <div className="mt-4 grid gap-3 md:grid-cols-2">
      <h3 className="font-semibold text-sm md:col-span-2">{zh ? 'AI 条件式推演 · 不属于已核实事实' : 'AI hypotheses · not verified facts'}</h3>
      {(['transmission', 'beneficiaries', 'risks', 'countercase', 'horizon', 'confirmation', 'invalidation'] as const).map((field, i) => <div key={field} className="text-sm">
        <h4 className="text-xs text-secondary-text">{(zh ? ['影响路径', '潜在受益方向', '承压方向 / 风险', '反向情景', '影响周期', '后续验证', '失效条件'] : ['Transmission', 'Potential beneficiaries', 'Risks', 'Countercase', 'Horizon', 'Confirmation', 'Invalidation'])[i]}</h4><p className="mt-1 whitespace-pre-wrap break-words">{analysis[field]}</p>
      </div>)}
      {!!analysis.holding_links.length && <div className="md:col-span-2 text-sm"><h4 className="text-xs text-secondary-text">{zh ? '已记录持仓的可能关联（AI 推演）' : 'Potential recorded-holding links (AI inference)'}</h4>{analysis.holding_links.map((h) => <p key={`${h.market}-${h.symbol}`} className="mt-1">{h.symbol} ({h.market}): {h.reason}</p>)}</div>}
    </div> : !blocked && <p className="mt-3 text-xs text-secondary-text">{zh ? '解读状态：' : 'Interpretation: '}{statusLabel(event.analysis_status, zh)}</p>}
    <details className="mt-4 text-sm"><summary className="cursor-pointer">{zh ? '核验 / 更正记录（人工）' : 'Verification / corrections (human)'}</summary>
      <p className="text-xs my-2">{zh ? '必须阅读原文再确认。这里只记录你的核验及依据，不是系统对真实性的认证；旧快照不会被覆盖。' : 'Read the original before attesting. This records your review, not automated certification. Old snapshots remain unchanged.'}</p>
      {reviews.map((r, i) => <p key={i} className="text-xs mb-2">{stamp(r.checked_at, zh)} · {statusLabel(r.status, zh)} · <Link url={r.evidence_url}>{r.note}</Link></p>)}
      {error && <InlineAlert variant="danger" message={error} />}
      <form onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); setBusy(true); setError('');
        marketEventsApi.verify(brief.id, { event_key: event.event_key, status: String(f.get('status')), evidence_url: String(f.get('url')), note: String(f.get('note')) })
          .then(onVerified).catch((err) => setError(getParsedApiError(err).message)).finally(() => setBusy(false)); }}>
        <fieldset disabled={busy} className="space-y-2">
          <label className="block text-xs">{zh ? '核验结论' : 'Review status'}<select name="status" className={inputClass}>{['unverified', 'confirmed', 'disputed', 'retracted'].map((s) => <option key={s} value={s}>{statusLabel(s, zh)}</option>)}</select></label>
          <label className="block text-xs">{zh ? '支持 / 辟谣原文链接' : 'Supporting / correction URL'}<input name="url" type="url" className={inputClass} required maxLength={2000} /></label>
          <label className="block text-xs">{zh ? '核验了哪些具体条款（至少 10 字符）' : 'Specific reviewed claims (min. 10 characters)'}<textarea name="note" className={inputClass} required minLength={10} maxLength={1000} /></label>
          <button className="btn-secondary text-xs">{zh ? '保存核验记录' : 'Save review'}</button>
        </fieldset>
      </form>
    </details>
  </Card>;
}

function SourceSettings({ zh }: { zh: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [sources, setSources] = useState<NewsSource[]>([]);
  const [templates, setTemplates] = useState<SourceTemplate[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => { const [s, t] = await Promise.all([marketEventsApi.sources(), marketEventsApi.templates()]); setSources(s.items); setTemplates(t.items); };
  const run = async (action: () => Promise<unknown>) => { setBusy(true); setError(''); try { await action(); await load(); } catch (e) { setError(getParsedApiError(e).message); } finally { setBusy(false); } };
  return <Card><button className="text-sm" aria-expanded={expanded} onClick={() => { setExpanded(!expanded); if (!expanded) void run(async () => undefined); }}>{zh ? '资讯源设置' : 'Feed settings'}</button>
    {expanded && <fieldset disabled={busy} className="mt-3 space-y-3">
      <p className="text-xs text-secondary-text">{zh ? 'NewsNow 默认是公共示例实例，可能限流或不可用。启用表示同意后续访问；不会立即采集或新增定时任务。已有全局自动采集开关仍按原配置工作。' : 'NewsNow defaults to a public demo instance and may fail or throttle. Enabling allows later access, not immediate fetching or a new schedule. Existing global auto-fetch configuration still applies.'}</p>
      {error && <InlineAlert variant="danger" message={error} />}
      {sources.map((s) => <label className="block text-xs" key={s.id}><input type="checkbox" checked={s.enabled} onChange={(e) => void run(() => marketEventsApi.enableSource(s.id, e.target.checked))} /> {s.name} · {s.market} · {s.last_status ?? '—'}</label>)}
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); void run(() => marketEventsApi.addSource(String(f.get('template')))); }}>
        <select className={`${inputClass} md:max-w-md`} name="template" aria-label={zh ? '资讯源模板' : 'Feed template'} required><option value="">{zh ? '选择资讯源模板' : 'Choose feed template'}</option>{templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.name} · {t.market}</option>)}</select>
        <button className="btn-secondary text-xs">{zh ? '添加并启用' : 'Add and enable'}</button>
      </form>
    </fieldset>}
  </Card>;
}
