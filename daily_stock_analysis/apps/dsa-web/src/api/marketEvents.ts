import apiClient from './index';

export type EventMarket = 'cn' | 'hk' | 'us' | 'global';
export type NewsEvidence = {
  evidence_id: string; title: string; summary: string; source: string; url: string;
  published_at: string | null; published_at_raw: string; time_precision: string;
  event_at: string | null; first_seen_at: string; retrieved_at: string; source_tier: string;
};
export type EventAnalysis = {
  transmission: string; beneficiaries: string; risks: string; countercase: string; horizon: string;
  confirmation: string; invalidation: string;
  holding_links: Array<{ symbol: string; market: string; reason: string }>;
};
export type MarketEvent = {
  event_key: string; title: string; evidence: NewsEvidence[]; time_bucket: string; topics: string[];
  priority_score: number; verification: string; analysis: EventAnalysis | null; analysis_status: string;
  market_relevance?: string; primary_topic?: string;
};
export type Verification = {
  event_key: string; status: string; evidence_url: string; note: string; checked_at: string; authority: string;
};
export type EventCoverage = {
  analysis_failure?: string | null; empty_reason?: string | null;
  status: string; analysis_status: string; collected_count: number; candidate_count: number; not_selected: number;
  excluded: Record<string, number>;
  sources: Array<{ source: string; status: string; count?: number; truncated?: boolean; query?: string }>;
};
export type BriefSummary = { id: number; market: EventMarket; captured_at: string; language: string; coverage: EventCoverage;
  parent_brief_id?: number; analysis_retried_at?: string };
export type EventBrief = BriefSummary & {
  candidate_events?: MarketEvent[];
  coverage_audit?: { baseline_id: number | null; baseline_at: string | null; scope: string;
    rows: Array<{ sector: string; label_zh: string; label_en: string; state: string }> };
  sector_radar?: Array<{ sector: string; label_zh: string; label_en: string; state: string;
    event_keys: string[]; eligible_event_keys: string[]; executable: false }>;
  timezone: string; events: MarketEvent[]; markdown: string; holding_status: string;
  holdings: Array<{ symbol: string; market: string }>; verification_history?: Verification[];
  holding_context?: { status?: string; profile_date?: string | null; revision?: string };
};
export type BriefInput = {
  request_key: string; market: EventMarket; language: 'zh' | 'en'; refresh_sources: boolean;
  search_news: boolean; analyze: boolean; scan_sectors?: boolean;
  manual_items: Array<{ title: string; summary: string; url: string; published_at: string; event_at?: string }>;
};
export type NewsSource = { id: number; name: string; enabled: boolean; market: string; last_status?: string };
export type SourceTemplate = { template_id: string; name: string; market: string };

export type NewsJob = { status: string; stage: string; brief_id: number | null };
export class NewsJobFailed extends Error {}
type Progress = (job: NewsJob) => void;
function pause(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('aborted')); return; }
    const abort = () => { clearTimeout(timer); reject(new Error('aborted')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, 1500);
    signal?.addEventListener('abort', abort, { once: true });
  });
}

async function waitForJob(key: string, update?: Progress, signal?: AbortSignal, first?: NewsJob): Promise<EventBrief> {
  for (let attempt = 0; attempt < 400; attempt++) {
    const job = attempt === 0 && first ? first :
      (await apiClient.get<NewsJob>(`/api/v1/market-events/jobs/${key}`, { signal })).data;
    update?.(job);
    if (job.status === 'completed' && job.brief_id != null) {
      return (await apiClient.get<EventBrief>(`/api/v1/market-events/${job.brief_id}`, { signal })).data;
    }
    if (['failed', 'cancelled'].includes(job.status)) throw new NewsJobFailed('market_event_job_failed');
    if (job.status === 'unknown') throw new Error('market_event_job_unknown');
    await pause(signal);
  }
  throw new Error('market_event_wait_timeout');
}

export const marketEventsApi = {
  async list(market: EventMarket) {
    return (await apiClient.get<{ items: BriefSummary[] }>('/api/v1/market-events', { params: { market } })).data;
  },
  async get(id: number) { return (await apiClient.get<EventBrief>(`/api/v1/market-events/${id}`)).data; },
  async generate(input: BriefInput, update?: Progress, signal?: AbortSignal) {
    const job = (await apiClient.post<NewsJob>('/api/v1/market-events/jobs', input, { signal })).data;
    return waitForJob(input.request_key, update, signal, job);
  },
  async retryAnalysis(id: number, key: string, update?: Progress, signal?: AbortSignal) {
    const job = (await apiClient.post<NewsJob>(`/api/v1/market-events/${id}/retry-analysis`, { request_key: key }, { signal })).data;
    return waitForJob(key, update, signal, job);
  },
  waitForJob,
  async verify(id: number, input: Pick<Verification, 'event_key' | 'status' | 'evidence_url' | 'note'>) {
    return (await apiClient.post<Verification>(`/api/v1/market-events/${id}/verifications`, input)).data;
  },
  async sources() { return (await apiClient.get<{ items: NewsSource[] }>('/api/v1/intelligence/sources')).data; },
  async templates() { return (await apiClient.get<{ items: SourceTemplate[] }>('/api/v1/intelligence/sources/templates')).data; },
  async addSource(template: string) {
    return (await apiClient.post(`/api/v1/intelligence/sources/templates/${template}`, { enabled: true })).data;
  },
  async enableSource(id: number, enabled: boolean) {
    return (await apiClient.patch(`/api/v1/intelligence/sources/${id}`, { enabled })).data;
  },
};
