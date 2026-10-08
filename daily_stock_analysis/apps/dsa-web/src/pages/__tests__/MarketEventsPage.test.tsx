import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MarketEventsPage from '../MarketEventsPage';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import type { EventBrief } from '../../api/marketEvents';

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), generate: vi.fn(), retryAnalysis: vi.fn(), waitForJob: vi.fn(), verify: vi.fn(), sources: vi.fn(), templates: vi.fn(), addSource: vi.fn(), enableSource: vi.fn() }));
vi.mock('../../api/marketEvents', () => ({ marketEventsApi: api, NewsJobFailed: class extends Error {} }));
const eventKey = 'a'.repeat(64);
const brief = (patch: Partial<EventBrief> = {}): EventBrief => ({ id: 1, market: 'cn', language: 'zh', captured_at: '2026-09-29T11:00:00Z', timezone: 'Asia/Shanghai',
  coverage: { status: 'partial', analysis_status: 'available', collected_count: 1, candidate_count: 1, not_selected: 0,
    excluded: { old: 1, future_publication: 0 }, sources: [{ source: 'feed', status: 'failed' }] },
  holding_status: 'no_recorded_holdings', holdings: [], markdown: 'Frozen brief', verification_history: [],
  events: [{ event_key: eventKey, title: 'Test policy claim', time_bucket: 'time_unknown', topics: ['macro'], priority_score: 3,
    verification: 'reported', analysis_status: 'available',
    evidence: [{ evidence_id: 'e1', title: 'Test policy claim', summary: 'Source claim is not a confirmed fact.', source: 'Fixture',
      url: 'https://example.com/news', published_at: null, published_at_raw: '', time_precision: 'unknown', event_at: null,
      first_seen_at: '2026-09-29T11:00:00Z', retrieved_at: '2026-09-29T11:00:00Z', source_tier: 'reported' }],
    analysis: { transmission: 'Conditional effect', beneficiaries: 'Potential industries', risks: 'Risk evidence', countercase: 'May not happen',
      horizon: 'One week', confirmation: 'Read original', invalidation: 'Withdrawal', holding_links: [] } }], ...patch });
const mount = () => render(<UiLanguageProvider><MarketEventsPage /></UiLanguageProvider>);

describe('MarketEventsPage', () => {
  beforeEach(() => {
    vi.resetAllMocks(); sessionStorage.clear(); localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    api.list.mockResolvedValue({ items: [] }); api.get.mockResolvedValue(brief()); api.generate.mockResolvedValue(brief());
    api.sources.mockResolvedValue({ items: [] }); api.templates.mockResolvedValue({ items: [] });
  });
  it('reads history only on mount, no external fetch or mutation', async () => {
    mount(); await screen.findByText(/尚未生成事件简报/);
    expect(api.generate).not.toHaveBeenCalled(); expect(api.sources).not.toHaveBeenCalled(); expect(api.addSource).not.toHaveBeenCalled();
  });
  it('separates cross-sector evidence from holdings and sends the scan choice', async () => {
    api.generate.mockResolvedValue(brief({ sector_radar: [{ sector: 'cybersecurity', label_zh: '网络安全', label_en: 'Cybersecurity',
      state: 'evidence_watch', event_keys: [eventKey], eligible_event_keys: [eventKey], executable: false }] }));
    mount(); await screen.findByText(/尚未生成事件简报/);
    fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText('跨行业机会 · 证据观察池');
    expect(api.generate.mock.calls[0][0].scan_sectors).toBe(true);
    expect(screen.getByText('网络安全')).toBeInTheDocument();
    expect(screen.getByText(/未覆盖不等于没有机会/)).toBeInTheDocument();
  });
  it('displays real progress and aborts polling on unmount, not server work', async () => {
    api.generate.mockImplementation((_input, update) => {
      update({ status: 'processing', stage: 'interpreting', brief_id: null });
      return new Promise(() => {});
    });
    const view = mount(); await screen.findByText(/尚未生成事件简报/);
    fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText(/阶段不是时间完成百分比/);
    expect(screen.getByText(/生成条件式解读 ·/)).toBeInTheDocument();
    const signal = api.generate.mock.calls[0][2];
    view.unmount(); expect(signal.aborted).toBe(true);
    expect(sessionStorage.getItem('dsa.news.pending.cn.zh')).toBeTruthy();
  });
  it('shows omitted candidate sources and frozen coverage audit without claiming a buy', async () => {
    const candidate = { ...brief().events[0], event_key: 'b'.repeat(64), title: '固态电池合成测试线索' };
    api.generate.mockResolvedValue(brief({ candidate_events: [candidate], sector_radar: [{
      sector: 'batteries', label_zh: '电池 / 固态电池 / 储能', label_en: 'Batteries', state: 'verification_required',
      event_keys: [candidate.event_key], eligible_event_keys: [], executable: false,
    }], coverage_audit: { baseline_id: 9, baseline_at: '2026-09-29T01:13:00Z', scope: 'same_day_news_coverage_not_trade_performance',
      rows: [{ sector: 'batteries', label_zh: '电池', label_en: 'Batteries', state: 'previously_collected_not_selected' }] } }));
    mount(); await screen.findByText(/尚未生成事件简报/);
    expect(screen.getByText(/另加 5 组检索/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText('固态电池合成测试线索');
    expect(screen.getByText(/未入选正文/)).toBeInTheDocument();
    expect(screen.getByText(/此前收集到但未入选/)).toBeInTheDocument();
    expect(screen.getByText(/不证明盘前可买/)).toBeInTheDocument();
  });
  it('recovers a stored request by status lookup only', async () => {
    sessionStorage.setItem('dsa.news.pending.cn.zh', 'pending_request_0001');
    api.waitForJob.mockResolvedValue(brief());
    mount(); await screen.findByText(/尚未生成事件简报/);
    fireEvent.click(screen.getByText('检查上次任务状态（不重新生成）'));
    await screen.findByText('Test policy claim');
    expect(api.waitForJob).toHaveBeenCalledWith('pending_request_0001', expect.any(Function), expect.any(AbortSignal));
    expect(api.generate).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('dsa.news.pending.cn.zh')).toBeNull();
  });
  it('retries only on click and labels frozen evidence revisions', async () => {
    const missing = brief(); missing.events[0].analysis = null;
    missing.coverage.analysis_failure = 'model_empty';
    api.list.mockResolvedValue({ items: [missing] }); api.get.mockResolvedValue(missing);
    api.retryAnalysis.mockResolvedValue(brief({ id: 2, parent_brief_id: 1, analysis_retried_at: '2026-09-30T11:00:00Z' }));
    mount(); await screen.findByText('Test policy claim');
    expect(api.retryAnalysis).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('仅重试缺失解读（可能计费）'));
    await screen.findByText(/本次只补解读，没有刷新新闻或持仓/);
    expect(api.retryAnalysis).toHaveBeenCalledWith(1, expect.any(String), expect.any(Function), expect.any(AbortSignal));
    expect(api.generate).not.toHaveBeenCalled();
  });
  it('keeps partial coverage, unknown time and AI inference visibly separate', async () => {
    api.list.mockResolvedValue({ items: [brief()] }); mount();
    await screen.findByText('Test policy claim');
    expect(screen.getByText(/覆盖不完整/)).toBeInTheDocument();
    expect(screen.getByText(/发布时间待核实/)).toBeInTheDocument();
    expect(screen.getByText(/AI 条件式推演 · 不属于已核实事实/)).toBeInTheDocument();
    expect(screen.getByText(/未读取到已记录持仓/)).toBeInTheDocument();
  });
  it('generates only by explicit click, without enabling feeds or backdating', async () => {
    mount(); await screen.findByText(/尚未生成事件简报/); fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText('Test policy claim');
    expect(api.generate).toHaveBeenCalledWith(expect.objectContaining({ market: 'cn', language: 'zh', refresh_sources: false, search_news: true, analyze: true }), expect.any(Function), expect.any(AbortSignal));
    expect(api.generate.mock.calls[0][0]).not.toHaveProperty('as_of');
    expect(api.addSource).not.toHaveBeenCalled();
  });
  it('reuses an idempotency key after an uncertain failure', async () => {
    api.generate.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce(brief());
    mount(); await screen.findByText(/尚未生成事件简报/); fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText(/服务端访问外部依赖时超时/); fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText('Test policy claim');
    expect(api.generate.mock.calls[0][0].request_key).toEqual(api.generate.mock.calls[1][0].request_key);
  });
  it('does not show a late response for the previously selected market', async () => {
    let finish!: (v: EventBrief) => void;
    api.generate.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    mount(); await screen.findByText(/尚未生成事件简报/); fireEvent.click(screen.getByText('生成今日简报'));
    fireEvent.change(screen.getByLabelText('研究市场'), { target: { value: 'us' } });
    await screen.findByText(/尚未生成事件简报/); await act(async () => finish(brief()));
    expect(screen.queryByText('Test policy claim')).not.toBeInTheDocument();
  });
  it('hides current interpretation when a later human review retracts the news', async () => {
    api.list.mockResolvedValue({ items: [brief()] });
    api.get.mockResolvedValue(brief({ verification_history: [{ event_key: eventKey, status: 'retracted', evidence_url: 'https://example.com/correction',
      note: 'Correction reviewed', checked_at: '2026-09-29T12:00:00Z', authority: 'user_attestation' }] }));
    mount(); await screen.findByText('Test policy claim');
    expect(screen.queryByText('Conditional effect')).not.toBeInTheDocument();
    expect(screen.getByText(/旧解读不再作为当前判断依据/)).toBeInTheDocument();
    expect(api.verify).not.toHaveBeenCalled();
  });
  it('does not mistake an empty result for no market news', async () => {
    api.list.mockResolvedValue({ items: [brief()] }); api.get.mockResolvedValue(brief({ events: [] }));
    mount(); await screen.findByText(/不代表今天没有重大消息/);
  });
  it('distinguishes opt-in profile context from a trade ledger and timestamps', async () => {
    api.list.mockResolvedValue({ items: [brief()] });
    api.get.mockResolvedValue(brief({ holding_status: 'profile_reference', holdings: [{ symbol: 'TSLA', market: 'us' }],
      holding_context: { status: 'profile_reference', profile_date: '2026-09-29' } }));
    mount(); await screen.findByText(/投资档案参考（仅代码，非交易账本）/);
    expect(screen.getByText(/档案版本日期（非成交或估值日期）/)).toBeInTheDocument();
    expect(screen.getByText(/不传数量、金额、成本或档案原文/)).toBeInTheDocument();
    expect(api.generate).not.toHaveBeenCalled();
  });
  it('shows a stale profile as paused rather than no holdings', async () => {
    api.list.mockResolvedValue({ items: [brief()] });
    api.get.mockResolvedValue(brief({ holding_status: 'profile_stale', holdings: [],
      holding_context: { status: 'profile_stale', profile_date: '2026-09-01' } }));
    mount(); await screen.findByText(/投资档案超过 7 天，已暂停关联/);
    expect(screen.queryByText(/未读取到已记录持仓/)).not.toBeInTheDocument();
  });
  it('keeps scheduled occurrence distinct from publication and passes it only on submit', async () => {
    const scheduled = brief(); scheduled.events[0].time_bucket = 'upcoming_event';
    scheduled.events[0].market_relevance = 'explicit_market';
    scheduled.events[0].evidence[0].event_at = '2026-09-30T20:30:00Z';
    api.generate.mockResolvedValue(scheduled);
    mount(); await screen.findByText(/尚未生成事件简报/);
    fireEvent.change(screen.getByLabelText('标题'), { target: { value: '财报电话会预告' } });
    fireEvent.change(screen.getByLabelText('发布时间，含时区；不明留空'), { target: { value: '2026-08-26' } });
    fireEvent.change(screen.getByLabelText('事件预定 / 发生时间，含时区（可空）'), { target: { value: '2026-09-30T16:30:00-04:00' } });
    expect(api.generate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('生成今日简报'));
    await screen.findByText(/未来已排期，尚未发生/);
    expect(api.generate.mock.calls[0][0].manual_items[0]).toEqual(expect.objectContaining({
      published_at: '2026-08-26', event_at: '2026-09-30T16:30:00-04:00',
    }));
    expect(screen.getByText(/涉及研究市场/)).toBeInTheDocument();
  });
  it('provides English labels and explicit source opt-in', async () => {
    localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    api.templates.mockResolvedValue({ items: [{ template_id: 'jin10', name: 'News feed', market: 'global' }] });
    mount(); await screen.findByText(/No event brief yet/); fireEvent.click(screen.getByText('Feed settings'));
    await screen.findByText('News feed · global');
    expect(api.addSource).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Feed template'), { target: { value: 'jin10' } });
    fireEvent.submit(screen.getByText('Add and enable').closest('form')!);
    await waitFor(() => expect(api.addSource).toHaveBeenCalledWith('jin10'));
    expect(api.generate).not.toHaveBeenCalled();
  });
  it('saves human evidence and updates the overlay without overwriting source facts', async () => {
    api.list.mockResolvedValue({ items: [brief()] }); api.verify.mockResolvedValue({ event_key: eventKey, status: 'disputed',
      evidence_url: 'https://example.com/correction', note: 'Specific disputed policy terms', checked_at: '2026-09-29T12:00:00Z', authority: 'user_attestation' });
    mount(); await screen.findByText('Test policy claim');
    fireEvent.change(screen.getByLabelText('核验结论'), { target: { value: 'disputed' } });
    fireEvent.change(screen.getByLabelText('支持 / 辟谣原文链接'), { target: { value: 'https://example.com/correction' } });
    fireEvent.change(screen.getByLabelText('核验了哪些具体条款（至少 10 字符）'), { target: { value: 'Specific disputed policy terms' } });
    fireEvent.submit(screen.getByText('保存核验记录').closest('form')!);
    await screen.findByText(/旧解读不再作为当前判断依据/);
    expect(screen.getByText('Source claim is not a confirmed fact.')).toBeInTheDocument();
    expect(screen.queryByText('Conditional effect')).not.toBeInTheDocument();
  });
});
