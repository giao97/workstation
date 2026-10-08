import { useEffect, useRef, useState } from 'react';
import { portfolioApi } from '../../api/portfolio';
import { getParsedApiError } from '../../api/error';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { InlineAlert } from '../common';
import type { AllocationReview, AllocationReviewList, AllocationReviewWrite, AllocationStatus } from '../../types/portfolio';

const inputClass = 'input-surface rounded-lg border px-3 py-2 text-sm w-full';
const horizons = ['long_term', 'tactical'] as const;
const decisions = ['maintain_plan', 'wait', 'data_required', 'pause'] as const;
const decisionText = (value: AllocationReviewWrite['decision'], zh: boolean) => zh
  ? { maintain_plan: '配置计划维持', wait: '等待', data_required: '补数据', pause: '暂停研究计划' }[value]
  : value.replaceAll('_', ' ');
const trackText = (track: AllocationReviewWrite['horizon'], zh: boolean) => zh
  ? (track === 'long_term' ? '长期配置' : '短线择时') : track.replaceAll('_', ' ');

export function AllocationReviewPanel({ status }: { status: AllocationStatus }) {
  const { language } = useUiLanguage(); const zh = language === 'zh';
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(status.targets[0]?.key ?? '');
  return <section className="rounded-xl border border-border p-3 text-sm">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="font-medium">
      {zh ? '长期配置 / 短线复核' : 'Long-term / tactical review'} {open ? '−' : '+'}
    </button>
    {open && <div className="mt-3 space-y-3">
      <p className="text-xs text-secondary">{zh
        ? '两个维度独立记录：短线等待不修改长期目标或共享预算。到期只标记重审，不自动买入、续期或新增通知任务。人工证据尚未独立核验；已开启日报的计划会将记录附入既有简报。'
        : 'Independent tracks: tactical waiting does not change targets or shared budgets. Due reviews do not trigger trades, renewal or notifications. Manual evidence is unverified; opted-in plans include these records in existing daily reports.'}</p>
      <label>{zh ? '复核资产' : 'Review asset'}<select className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)}>
        {status.targets.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}
      </select></label>
      {target && <ReviewTrack key={`${status.planId}:${status.planVersion}:${target}`}
        planId={status.planId} version={status.planVersion} target={target} zh={zh} />}
    </div>}
  </section>;
}

function ReviewTrack({ planId, version, target, zh }: { planId: number; version: number; target: string; zh: boolean }) {
  const [data, setData] = useState<AllocationReviewList | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0); const [horizon, setHorizon] = useState<typeof horizons[number]>('long_term');
  const [now, setNow] = useState(Date.now);
  const requests = useRef(0);
  useEffect(() => {
    const request = ++requests.current;
    portfolioApi.getAllocationReviews(planId, target).then((value) => {
      if (requests.current === request) { setData(value); setError(''); }
    }).catch((err) => { if (requests.current === request) setError(getParsedApiError(err).message); });
    return () => { requests.current += 1; };
  }, [planId, target, refresh]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer); }, []);
  const reload = () => { setData(null); setRefresh((value) => value + 1); };
  const stateText = (item: AllocationReview) => {
    const state = item.state === 'active' && Date.parse(item.reviewDueAt) <= now ? 'due' : item.state;
    return zh ? { active: '待按条件复核', due: '已到复核时间', plan_changed: '计划已变更，旧判断待重审', plan_inactive: '计划停用' }[state] : state.replaceAll('_', ' ');
  };
  const dateText = (value: string) => new Date(value).toLocaleString(zh ? 'zh-CN' : 'en-US', { timeZoneName: 'short' });
  const save = async (value: AllocationReviewWrite) => {
    const request = requests.current;
    setBusy(true); setError('');
    try { await portfolioApi.saveAllocationReview(planId, value); if (requests.current === request) reload(); }
    catch (err) { if (requests.current === request) setError(getParsedApiError(err).message); }
    finally { if (requests.current === request) setBusy(false); }
  };
  const older = async () => {
    if (!data?.nextBeforeId) return;
    const request = requests.current;
    setBusy(true);
    try {
      const page = await portfolioApi.getAllocationReviews(planId, target, data.nextBeforeId);
      if (requests.current === request) setData({ ...data, items: [...data.items, ...page.items], nextBeforeId: page.nextBeforeId });
    } catch (err) { if (requests.current === request) setError(getParsedApiError(err).message); }
    finally { if (requests.current === request) setBusy(false); }
  };
  return <div className="space-y-3">
    {error && <InlineAlert variant="danger" message={error} />}
    <button type="button" className="btn-secondary text-xs" disabled={busy} onClick={reload}>{zh ? '刷新复核记录' : 'Refresh reviews'}</button>
    {!data ? <p>{error ? (zh ? '记录加载失败，请重试。' : 'Could not load reviews. Please retry.') : (zh ? '正在读取复核记录…' : 'Loading reviews…')}</p> : <>
      <div className="grid gap-3 md:grid-cols-2">{horizons.map((track) => {
        const item = data.latest.find((entry) => entry.horizon === track);
        return <div key={track} className="rounded-lg border border-border p-3 space-y-1 break-words">
          <h4 className="font-medium">{trackText(track, zh)}</h4>
          {!item ? <p className="text-secondary">{zh ? '尚无复核，不默认允许操作' : 'No review; no permission to trade'}</p> : <>
            <p>{decisionText(item.decision, zh)} · {stateText(item)}</p>
            <p>{item.reason}</p><p className="text-secondary">{item.evidence}</p>
            <p>{zh ? '复核条件：' : 'Review condition: '}{item.nextCondition}</p>
            <p>{zh ? '最迟复核：' : 'Review by: '}{dateText(item.reviewDueAt)}</p>
            <p className="text-xs text-secondary">v{item.expectedPlanVersion} / #{item.id} · {dateText(item.createdAt)}</p>
          </>}
        </div>;
      })}</div>
      {data.planVersion !== version ? <InlineAlert variant="warning" message={zh ? '计划版本已变化，请重新加载配置计划后再记录。' : 'Plan version changed. Reload the allocation plan before writing.'} /> : <>
        <label>{zh ? '记录维度' : 'Review track'}<select disabled={busy} className={inputClass} value={horizon} onChange={(e) => setHorizon(e.target.value as typeof horizon)}>
          {horizons.map((track) => <option key={track} value={track}>{trackText(track, zh)}</option>)}
        </select></label>
        <ReviewForm key={`${horizon}:${refresh}`} zh={zh} busy={busy} horizon={horizon} target={target} version={version}
          previousId={data.latest.find((item) => item.horizon === horizon)?.id ?? null} onSave={save} />
      </>}
      <details><summary className="cursor-pointer">{zh ? '追加历史（新 → 旧，不覆盖）' : 'Append-only history (newest first)'}</summary>
        <ul className="space-y-3 mt-2">{data.items.map((item) => <li key={item.id} className="break-words text-xs border-t border-border pt-2">
          #{item.id} ← {item.expectedPreviousId == null ? '—' : `#${item.expectedPreviousId}`} · {trackText(item.horizon, zh)} · {decisionText(item.decision, zh)} · {dateText(item.createdAt)}
          <p>{item.reason}</p><p>{item.evidence}</p><p>{item.nextCondition} · {dateText(item.reviewDueAt)}</p>
        </li>)}</ul>
        {data.nextBeforeId != null && <button type="button" className="btn-secondary mt-2" disabled={busy} onClick={older}>{zh ? '读取更早记录' : 'Load older reviews'}</button>}
      </details>
    </>}
  </div>;
}

function ReviewForm({ zh, busy, horizon, target, version, previousId, onSave }: {
  zh: boolean; busy: boolean; horizon: AllocationReviewWrite['horizon']; target: string; version: number;
  previousId: number | null; onSave: (value: AllocationReviewWrite) => Promise<void>;
}) {
  const [decision, setDecision] = useState<AllocationReviewWrite['decision']>('data_required');
  const [reason, setReason] = useState(''); const [evidence, setEvidence] = useState('');
  const [condition, setCondition] = useState(''); const [due, setDue] = useState('');
  const request = useRef<{ fingerprint: string; key: string } | null>(null);
  return <form onSubmit={(event) => {
    event.preventDefault(); if (busy || !due) return;
    const payload = { expectedPlanVersion: version, expectedPreviousId: previousId, targetKey: target,
      horizon, decision, reason: reason.trim(), evidence: evidence.trim(), nextCondition: condition.trim(), reviewDueAt: new Date(due).toISOString() };
    const fingerprint = JSON.stringify(payload);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() };
    void onSave({ ...payload, requestKey: request.current.key });
  }}><fieldset disabled={busy} className="space-y-3">
    <label className="block">{zh ? '研究结论（非交易指令）' : 'Research decision (not an order)'}<select className={inputClass} value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
      {decisions.map((value) => <option key={value} value={value}>{decisionText(value, zh)}</option>)}
    </select></label>
    <label className="block">{zh ? '本次理由' : 'Reason'}<textarea required maxLength={2000} className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
    <label className="block">{zh ? '新增证据 / 仍缺数据（含来源与时间）' : 'New evidence / missing data (source and time)'}<textarea required maxLength={4000} className={inputClass} value={evidence} onChange={(e) => setEvidence(e.target.value)} /></label>
    <label className="block">{zh ? '下次复核条件 / 失效条件' : 'Next review / invalidation condition'}<textarea required maxLength={2000} className={inputClass} value={condition} onChange={(e) => setCondition(e.target.value)} /></label>
    <label className="block">{zh ? '最迟复核时间（本机时区）' : 'Review deadline (local timezone)'}<input required type="datetime-local" className={inputClass} value={due} onChange={(e) => setDue(e.target.value)} /></label>
    <p className="text-xs text-secondary">{zh ? '维持计划不代表立即买入；只保存人工复核，不核验行情，不占用资金。' : 'Maintaining a plan is not permission to buy. Saves manual research only; does not validate quotes or reserve cash.'}</p>
    <button type="submit" className="btn-primary text-sm">{busy ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存复核（不交易）' : 'Save review (no trade)')}</button>
  </fieldset></form>;
}
