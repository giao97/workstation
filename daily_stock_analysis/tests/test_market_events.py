"""News claims, point-in-time evidence, safe model output and read-only holdings."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from api.v1.endpoints import market_events as endpoint
from src.config import Config
from src.core.market_events import encode, normalize_evidence, publication, safe_url
from src.repositories.market_event_repo import MarketEventRepository
from src.schemas.market_events import BriefRequest, VerificationRequest
from src.services.intelligence_service import IntelligenceService
from src.services.market_event_service import MarketEventService
from src.storage import (DatabaseManager, MarketNewsEvidence, MarketEventBrief, PortfolioAccount,
                         PortfolioTrade, PortfolioPosition)

NOW = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)


def raw(**patch):
    return dict(title='财政部：购房贷款政策提案', summary='仅为提案，具体细则待确认。',
                url='https://mof.gov.cn/policy/news.html', source='Ministry',
                published_at='2026-09-29T18:00:00+08:00', market='cn', **patch)


def request(**patch):
    data = dict(request_key='news_test_request_00001', market='cn', search_news=False, analyze=False)
    data.update(patch)
    return BriefRequest(**data)


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('ENV_FILE', str(tmp_path / 'missing.env'))
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'events.db'))
    Config.reset_instance()
    DatabaseManager.reset_instance()
    repo = MarketEventRepository()
    intel = IntelligenceService()
    clock = Mock(return_value=NOW)
    analyzer = Mock()
    analyzer.is_available.return_value = False
    search = Mock(is_available=False)
    service = MarketEventService(repo, intel, search, analyzer, clock, holdings_loader=lambda _: [])
    yield service, clock, analyzer, search
    DatabaseManager.reset_instance()
    Config.reset_instance()


def capture(service, rows=None, req=None, statuses=None):
    req = req or request()
    return service._capture(rows or [raw()], req, statuses or [{'source': 'test', 'status': 'ok'}], 'test-hash')


def count(repo, model):
    with repo.db.get_session() as session:
        return session.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize('value,precision', [
    ('2026-09-29', 'date_only'), ('2026-09-29T18:00:00', 'timezone_unknown'),
    ('Tue, 29 Sep 2026 10:00:00 GMT', 'timestamp'), ('2026-09-29T18:00:00+08:00', 'timestamp'),
    ('invalid', 'unknown'), ('2026-99-29', 'unknown'), (None, 'unknown'),
    (1790676000000, 'timestamp'),
])
def test_publication_never_guesses_timezones(value, precision):
    assert publication(value)[1] == precision


def test_sector_scan_is_bounded_and_each_failed_query_isolated(setup):
    service, _, _, search = setup
    search.is_available = True
    search.search_topic_news_bounded.side_effect = [TimeoutError('fixture')] + [
        SimpleNamespace(provider='fixture', success=True, results=[]) for _ in range(4)]
    _, statuses = service._collect(request(market='us', search_news=True))
    calls = search.search_topic_news_bounded.call_args_list
    assert len(calls) == 5 and all(c.kwargs['timeout_seconds'] == 12 for c in calls)
    assert any('cybersecurity' in c.args[0] for c in calls)
    assert sum(s['status'] == 'failed' for s in statuses) == 1
    search.reset_mock()
    search.search_topic_news_bounded.side_effect = None
    search.search_topic_news_bounded.return_value = SimpleNamespace(provider='fixture', success=True, results=[])
    service._collect(request(market='us', search_news=True, scan_sectors=False))
    assert search.search_topic_news_bounded.call_count == 2


def test_new_sector_evidence_not_misrepresented_as_holding_and_review_downgrades_radar(setup):
    service, *_ = setup
    news = {**raw(), 'title': 'US cybersecurity enterprise software earnings', 'market': 'us'}
    brief = capture(service, [news], request(market='us'))
    cyber = next(r for r in brief['sector_radar'] if r['sector'] == 'cybersecurity')
    assert cyber['state'] == 'evidence_watch' and not brief['holdings']
    key = brief['events'][0]['event_key']
    service.verify(brief['id'], VerificationRequest(event_key=key, status='retracted',
        evidence_url='https://example.com/correction', note='Fixture correction: withdrawn announcement'))
    latest = service.get(brief['id'])
    assert next(r for r in latest['sector_radar'] if r['sector'] == 'cybersecurity')['state'] == 'verification_required'


def test_candidate_pool_keeps_omitted_batteries_and_freezes_same_day_audit(setup):
    service, clock, *_ = setup
    rows = [{**raw(), 'title': f'A股电池订单{i}'} for i in range(4)]
    first = capture(service, rows)
    assert len(first['candidate_events']) == 4
    assert len(first['events']) == 2  # topic cap; evidence still visible
    assert len(next(r for r in first['sector_radar'] if r['sector'] == 'batteries')['event_keys']) == 4
    clock.return_value = NOW + timedelta(minutes=30)
    second = capture(service, rows, request(request_key='news_audit_second_01'))
    assert second['coverage_audit']['baseline_id'] == first['id']
    assert service.get(first['id'])['coverage_audit']['baseline_id'] is None
    assert '覆盖复盘' in second['markdown']
    clock.return_value = NOW + timedelta(days=1)
    third = capture(service, rows, request(request_key='news_audit_third_001'))
    assert third['coverage_audit']['baseline_id'] is None


def test_cn_scan_contains_batteries_and_market_led_discovery(setup):
    service, _, _, search = setup
    search.is_available = True
    search.search_topic_news_bounded.return_value = SimpleNamespace(provider='fixture', success=True, results=[])
    service._collect(request(search_news=True))
    queries = [c.args[0] for c in search.search_topic_news_bounded.call_args_list]
    assert len(queries) == 7
    assert any('固态电池' in q for q in queries)
    assert any('涨停梯队' in q for q in queries)


def test_final_sector_search_survives_two_full_local_pages(setup):
    service, *_ = setup
    rows = [{**raw(), 'title': f'财政政策{i}'} for i in range(248)]
    rows.append({**raw(), 'title': '固态电池热点尾部线索'})
    result = capture(service, rows)
    battery = next(r for r in result['sector_radar'] if r['sector'] == 'batteries')
    assert battery['event_keys']


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///secret', 'http://127.0.0.1/a',
    'https://user:password@public.example/a', 'http://169.254.169.254/a', 'http://localhost/a',
    'http://[::1]/a', 'https://internal.local/a', 'data:text/html,hello'])
def test_unsafe_links_never_render_or_fetch(url):
    assert safe_url(url) == ''


def test_secrets_and_tracking_stripped_from_links():
    assert safe_url('https://example.com/a?id=3&token=SECRET&utm_source=x#fragment') == 'https://example.com/a?id=3'


def test_old_and_future_excluded_missing_time_not_today(setup):
    service, *_ = setup
    rows = []
    for title, published in [('old', '2025-09-29T10:00:00Z'), ('future', '2026-09-29T12:00:00Z'),
                             ('unknown', ''), ('date only', '2026-09-29'), ('carryover', '2026-09-28T23:00:00Z')]:
        rows.append({**raw(), 'title': title, 'summary': '财政政策时点测试', 'published_at': published})
    result = capture(service, rows)
    assert result['coverage']['excluded'] == {'old': 1, 'future_publication': 1, 'unmatched_topic': 0, 'unmatched_market': 0}
    buckets = {e['title']: e['time_bucket'] for e in result['events']}
    assert buckets['unknown'] == 'time_unknown'
    assert buckets['date only'] == 'date_only'
    # 23:00 UTC is the following BJT day.
    assert buckets['carryover'] == 'today'


def test_us_day_boundary_and_no_historical_asof_api(setup):
    service, *_ = setup
    result = capture(service, [{**raw(), 'title': 'Fed rate decision', 'published_at': '2026-09-29T01:00:00Z'}], request(market='us'))
    assert result['events'][0]['time_bucket'] == 'carryover'
    with pytest.raises(ValidationError):
        request(as_of='2025-01-01')


def test_official_link_and_many_reposts_not_auto_confirmed(setup):
    service, *_ = setup
    result = capture(service, [raw(), {**raw(), 'url': 'https://news.example.com/a', 'source': 'Repost'}])
    assert len(result['events']) == 1
    event = result['events'][0]
    assert len(event['evidence']) == 2
    assert event['verification'] == 'reported'
    assert event['evidence'][0]['source_tier'] == 'primary_link'


def test_no_false_primary_suffix():
    assert normalize_evidence({**raw(), 'url': 'https://mof.gov.cn.attacker.example/a'}, NOW)['source_tier'] == 'reported'


def test_same_url_corrections_and_first_seen_are_immutable(setup):
    service, clock, *_ = setup
    original = capture(service)
    clock.return_value = NOW + timedelta(minutes=10)
    same = capture(service, req=request(request_key='news_second_request_0002'))
    first = original['events'][0]['evidence'][0]
    assert same['events'][0]['evidence'][0]['first_seen_at'] == first['first_seen_at']
    corrected = capture(service, [{**raw(), 'summary': 'Correction: policy was withdrawn'}], request(request_key='news_third_request_00003'))
    assert corrected['events'][0]['evidence_ids'] != original['events'][0]['evidence_ids']
    assert count(service.repo, MarketNewsEvidence) == 2
    assert service.repo.get(original['id'])['events'][0]['evidence'][0]['summary'] == '仅为提案，具体细则待确认。'


def test_verification_overlay_does_not_rewrite_old_or_new_content(setup):
    service, clock, *_ = setup
    brief = capture(service)
    key = brief['events'][0]['event_key']
    clock.return_value = NOW + timedelta(minutes=1)
    review = VerificationRequest(event_key=key, status='retracted', evidence_url='https://mof.gov.cn/correction', note='原文澄清：先前标题并非已执行政策。')
    service.verify(brief['id'], review)
    result = service.get(brief['id'])
    assert result['events'][0]['verification'] == 'reported'
    assert result['verification_history'][-1]['status'] == 'retracted'
    again = capture(service, req=request(request_key='news_new_report_0002'))
    assert again['events'][0]['verification'] == 'retracted'
    changed = capture(service, [{**raw(), 'summary': 'New version'}], request(request_key='news_new_report_0003'))
    assert changed['events'][0]['verification'] == 'reported'


def test_failed_feed_is_partial_even_with_cached_evidence(setup):
    service, *_ = setup
    result = capture(service, statuses=[{'source': 'feed', 'status': 'failed'}, {'source': 'cache', 'status': 'cached'}])
    assert result['coverage']['status'] == 'partial'
    empty = capture(service, [{**raw(), 'published_at': '2020-01-01'}], request(request_key='empty_request_0000001'))
    assert empty['coverage']['status'] == 'insufficient'
    assert '不代表市场没有重大消息' in empty['markdown']


def interpretation(event, **patch):
    return dict(event_key=event['event_key'], evidence_ids=event['evidence_ids'], transmission='若政策落地，可能改善需求。',
        beneficiaries='相关产业', risks='执行风险', countercase='可能已被预期或未能落地', horizon='观察一周',
        confirmation='核对实施细则', invalidation='政策撤回', holding_links=[], **patch)


def test_model_has_schema_and_untrusted_boundary(setup):
    service, _, analyzer, _ = setup
    analyzer.is_available.return_value = True
    baseline = capture(service)
    event = baseline['events'][0]
    analyzer.generate_text.return_value = encode({'events': [interpretation(event)]})
    result = capture(service, req=request(request_key='news_analyzed_00001', analyze=True))
    assert result['events'][0]['analysis']['confirmation'] == '核对实施细则'
    assert result['events'][0]['verification'] == 'reported'
    assert 'UNTRUSTED_NEWS_DATA' in analyzer.generate_text.call_args.args[0]
    assert 'No trade instructions' in analyzer.generate_text.call_args.args[0]


@pytest.mark.parametrize('bad', ['citation', 'holding', 'extra', 'duplicate', 'non_json'])
def test_invalid_model_evidence_rejected_whole_batch(setup, bad):
    service, _, analyzer, _ = setup
    event = capture(service)['events'][0]
    item = interpretation(event)
    if bad == 'citation':
        item['evidence_ids'] = ['invented']
    elif bad == 'holding':
        item['holding_links'] = [{'symbol': 'HAL', 'market': 'us', 'reason': 'invented holding'}]
    elif bad == 'extra':
        item['buy_price'] = 25
    payload = {'events': [item, item] if bad == 'duplicate' else [item]}
    analyzer.is_available.return_value = True
    analyzer.generate_text.return_value = 'bad json' if bad == 'non_json' else encode(payload)
    result = capture(service, req=request(request_key='news_bad_model_00001', analyze=True))
    assert result['events'][0]['analysis'] is None
    assert result['coverage']['analysis_status'] == 'model_failed_or_invalid'


def test_idempotent_api_no_network_on_get_and_no_backdating(setup, monkeypatch):
    service, *_ = setup
    monkeypatch.setattr(endpoint, 'MarketEventService', lambda: service)
    app = FastAPI(); app.include_router(endpoint.router, prefix='/events')
    client = TestClient(app)
    body = request(manual_items=[{'title': '央行利率观察', 'summary': 'No timestamp available'}]).model_dump()
    first = client.post('/events', json=body)
    assert first.status_code == 200
    second = client.post('/events', json=body)
    assert second.json()['id'] == first.json()['id']
    assert count(service.repo, MarketEventBrief) == 1
    assert client.get(f"/events/{first.json()['id']}").status_code == 200
    assert client.post('/events', json={**body, 'market': 'us'}).status_code == 400
    assert client.post('/events', json={**body, 'as_of': '2025-09-29'}).status_code == 422
    assert client.get('/events/999999').status_code == 404
    assert count(service.repo, PortfolioTrade) == 0


def test_feed_raw_timezone_preserved_and_disabled_not_enabled(setup):
    service, *_ = setup
    entries = service.intelligence._parse_feed(b'<rss><channel><item><title>Rate policy</title><pubDate>Tue, 29 Sep 2026 18:00:00 +0800</pubDate></item></channel></rss>', source_name='test', limit=5)
    assert entries[0].raw_payload['published_at_raw'].endswith('+0800')
    source = service.intelligence.repo.create_source(dict(name='off', source_type='rss', url='https://example.com/feed', enabled=False, scope_type='market', market='cn'))
    result = service.generate(request(refresh_sources=True))
    assert service.intelligence.repo.get_source(source.id).enabled is False
    assert result['coverage']['status'] == 'insufficient'


def test_search_failure_and_no_model_are_visible(setup):
    service, _, analyzer, search = setup
    search.is_available = True
    search.search_topic_news_bounded.side_effect = TimeoutError('test only')
    result = service.generate(request(search_news=True, analyze=True, manual_items=[{'title': '财政政策快讯'}]))
    assert result['coverage']['status'] == 'partial'
    assert result['coverage']['analysis_status'] == 'model_unavailable'
    analyzer.generate_text.assert_not_called()


def test_recorded_holdings_replay_excludes_sold_zero_and_future_without_writes(setup):
    service, *_ = setup
    with service.repo.db.get_session() as session:
        account = PortfolioAccount(name='Synthetic', market='us', base_currency='USD', is_active=True)
        session.add(account); session.flush()
        for symbol, side, qty, day in [('VOO', 'buy', 2, 28), ('HAL', 'buy', 10, 28), ('HAL', 'sell', 10, 28), ('XYZ', 'buy', 1, 30)]:
            session.add(PortfolioTrade(account_id=account.id, symbol=symbol, market='us', currency='USD',
                side=side, quantity=qty, price=100, fee=1, tax=0, trade_date=date(2026, 9, day)))
        session.commit()
    positions = service._holdings(NOW)
    assert {(p['symbol'], p['market']) for p in positions} == {('VOO', 'us')}
    assert count(service.repo, PortfolioPosition) == 0
    assert count(service.repo, PortfolioTrade) == 4


def test_profile_context_is_market_scoped_and_never_creates_ledger(setup, tmp_path):
    from tests.test_market_event_holdings import PROFILE
    service, _, _, _ = setup
    path = tmp_path / 'profile.md'; path.write_text(PROFILE)
    service.intelligence.config.market_event_profile_path = str(path)
    service.holdings_loader = service._holdings
    result = capture(service, [{**raw(), 'title': 'VOO market outlook', 'market': 'us'}], request(market='us'))
    assert result['holding_status'] == 'profile_reference'
    assert {h['symbol'] for h in result['holdings']} == {'VOO', 'TSLA'}
    assert result['holding_context']['profile_date'] == '2026-09-29'
    prompt = service._prompt(result['events'], result['holdings'], 'zh')
    import json
    sent = json.loads(prompt.split('RECORDED_HOLDINGS:\n')[1].split('\nUNTRUSTED_NEWS_DATA:')[0])
    assert all(set(h) == {'symbol', 'market'} for h in sent)
    assert 'PRIVATE_' not in prompt and '518880' not in prompt
    for model in (PortfolioAccount, PortfolioTrade, PortfolioPosition):
        assert count(service.repo, model) == 0
    assert '投资档案参考（非交易账本）' in result['markdown'] and '2026-09-29' in result['markdown']


@pytest.mark.parametrize('active', [True, False])
def test_even_empty_or_inactive_ledger_accounts_prevent_profile_resurrection(setup, tmp_path, active):
    from tests.test_market_event_holdings import PROFILE
    service, *_ = setup
    path = tmp_path / 'profile.md'; path.write_text(PROFILE)
    service.intelligence.config.market_event_profile_path = str(path)
    with service.repo.db.get_session() as session:
        session.add(PortfolioAccount(name='Empty ledger', market='us', base_currency='USD', is_active=active))
        session.commit()
    assert service._holdings(NOW) == []


def test_stale_profile_remains_a_gap_not_an_empty_portfolio(setup, tmp_path):
    from tests.test_market_event_holdings import PROFILE
    service, *_ = setup
    path = tmp_path / 'profile.md'; path.write_text(PROFILE.replace('2026-09-29', '2026-09-01'))
    service.intelligence.config.market_event_profile_path = str(path)
    service.holdings_loader = service._holdings
    result = capture(service)
    assert result['holding_status'] == 'profile_stale' and result['holdings'] == []


def test_prompt_allowlist_removes_extra_holding_fields(setup):
    service, *_ = setup
    holdings = [{'symbol': 'VOO', 'market': 'us', 'cost': 'PRIVATE_COST', 'quantity': 999,
                 'account': 'PRIVATE_ACCOUNT', 'instruction': 'PRIVATE_INSTRUCTION'}]
    prompt = service._prompt([], holdings, 'en')
    assert 'PRIVATE_' not in prompt and '999' not in prompt


def test_report_capture_no_new_fetch_or_model_call(setup):
    service, _, analyzer, search = setup
    result = service.capture_report_news([SimpleNamespace(title='Fed rate decision', snippet='Reported claim', source='example',
        url='https://example.com/news', published_date='2026-09-29')], 'us', 'en', 'market_report_000001')
    assert result['events'][0]['time_bucket'] == 'date_only'
    analyzer.generate_text.assert_not_called()
    search.search_topic_news_bounded.assert_not_called()
    assert 'research, not trade signals' in result['markdown']


def test_no_more_than_eight_events_and_no_fake_probability(setup):
    service, *_ = setup
    result = capture(service, [{**raw(), 'title': f'{topic} {i}'} for topic in ('财政政策', '芯片', '回购', '石油') for i in range(3)])
    assert len(result['events']) == 8
    assert result['coverage']['not_selected'] == 4
    assert all('probability' not in item for item in result['events'])


def test_us_relevance_preserves_market_and_chip_news_over_foreign_local_policy(setup):
    service, *_ = setup
    titles = ['匈牙利央行暂停降息', '匈牙利央行评论国内经济', 'NVIDIA share repurchase announcement',
              'TSMC plans a U.S. chip-making hub', '美国消费者信心等待发布',
              '霍尔木兹海峡能源运输受扰', 'My retirement plan in Bali', '正在直播中']
    rows = [{**raw(), 'title': title, 'summary': '', 'market': 'global'} for title in titles]
    result = capture(service, rows, request(market='us'))
    selected = [e['title'] for e in result['events']]
    assert titles[0] not in selected and titles[1] not in selected
    assert titles[6] not in selected and titles[7] not in selected
    assert set(titles[2:6]) <= set(selected)
    assert result['coverage']['excluded']['unmatched_market'] == 2
    assert result['coverage']['excluded']['unmatched_topic'] == 2
    assert count(service.repo, MarketNewsEvidence) == len(rows)


def test_topic_caps_do_not_merge_distinct_claims_or_force_eight_slots(setup):
    service, *_ = setup
    result = capture(service, [{**raw(), 'title': f'美国原油运输消息 {i}', 'summary': '', 'market': 'global'} for i in range(10)], request(market='us'))
    assert len(result['events']) == 2
    assert result['coverage']['not_selected'] == 8
    assert len({e['event_key'] for e in result['events']}) == 2


def test_primary_notice_priority_is_not_truth_certification(setup):
    service, *_ = setup
    rows = [
        {**raw(), 'title': 'NVIDIA share repurchase authorization', 'summary': '', 'market': 'us',
         'url': 'https://nvidianews.nvidia.com/news/authorization', 'published_at': '2026-09-28'},
        {**raw(), 'title': 'NVIDIA stock commentary', 'summary': '', 'market': 'us',
         'url': 'https://example.com/commentary'},
    ]
    result = capture(service, rows, request(market='us'))
    first, second = result['events']
    assert first['title'] == rows[0]['title']
    assert first['priority_score'] > second['priority_score']
    assert first['verification'] == second['verification'] == 'reported'
    assert first['analysis'] is None


def test_distinct_occurrences_in_same_notice_do_not_merge(setup):
    service, *_ = setup
    rows = [{**raw(), 'title': '美国消费者信心预定发布', 'market': 'us', 'published_at': '2026-08-01',
             'event_at': f'2026-09-{day}T10:00:00-04:00'} for day in (29, 30)]
    result = capture(service, rows, request(market='us'))
    assert len(result['events']) == 2
    assert all(e['time_bucket'] == 'upcoming_event' for e in result['events'])
    assert len({e['event_key'] for e in result['events']}) == 2


def test_english_keyword_boundaries_do_not_match_oil_inside_turmoil(setup):
    service, *_ = setup
    result = capture(service, [{**raw(), 'title': 'Celebrity turmoil', 'summary': '', 'market': 'global'}], request(market='us'))
    assert result['events'] == []
    assert result['coverage']['excluded']['unmatched_topic'] == 1


def test_old_notice_retained_only_for_explicit_near_future_occurrence(setup):
    service, *_ = setup
    base = {**raw(), 'title': 'Micron earnings call scheduled', 'market': 'us', 'published_at': '2026-08-26',
            'event_at': '2026-09-30T16:30:00-04:00'}
    result = capture(service, [base], request(market='us'))
    assert result['events'][0]['time_bucket'] == 'upcoming_event'
    assert result['events'][0]['evidence'][0]['published_at'] == '2026-08-26'
    assert result['events'][0]['verification'] == 'reported'
    assert result['events'][0]['analysis'] is None
    assert 'scheduled future occurrence, not a released result' in service._prompt(result['events'], [], 'zh')
    for i, patch in enumerate([{'event_at': ''}, {'event_at': '2026-10-30T16:30:00-04:00'},
                                {'event_at': '2026-09-28T16:30:00-04:00'}, {'published_at': '2026-09-30'}]):
        rejected = capture(service, [{**base, **patch}], request(market='us', request_key=f'calendar_limit_{i:08d}'))
        assert rejected['events'] == []


def test_english_and_chinese_same_symbol_never_create_new_holdings(setup):
    service, *_ = setup
    service.holdings_loader = lambda _: [{'symbol': 'QQQM', 'market': 'us', 'basis': 'recorded_ledger'}]
    result = capture(service, [{**raw(), 'title': 'QQQM盘前观察', 'summary': '', 'market': 'global'}], request(market='us'))
    assert result['events'][0]['market_relevance'] == 'holding_mention'
    assert result['events'][0]['direct_mentions'] == [{'symbol': 'QQQM', 'market': 'us'}]


def test_model_context_bounded_and_cannot_cite_omitted_evidence(setup):
    service, _, analyzer, _ = setup
    rows = [{**raw(), 'url': f'https://example.com/repost-{i}'} for i in range(12)]
    event = capture(service, rows)['events'][0]
    sources = service._prompt([event], [], 'zh').split('UNTRUSTED_NEWS_DATA:\n')[1]
    import json
    selected = json.loads(sources)[0]
    assert len(selected['evidence']) == 3
    assert selected['omitted_evidence_count'] == 9
    assert len(event['evidence']) == 12
    item = interpretation(event)
    item['evidence_ids'] = [event['evidence_ids'][-1]]
    analyzer.is_available.return_value = True
    analyzer.generate_text.return_value = encode({'events': [item]})
    result = capture(service, rows, request(request_key='context_bounded_00001', analyze=True))
    assert result['coverage']['analysis_status'] == 'model_failed_or_invalid'


def test_retracted_event_stays_blocked_when_other_event_has_analysis(setup):
    service, clock, analyzer, _ = setup
    first = capture(service)
    clock.return_value = NOW + timedelta(minutes=1)
    service.verify(first['id'], VerificationRequest(event_key=first['events'][0]['event_key'], status='retracted',
        evidence_url='https://mof.gov.cn/correction', note='原文澄清：先前标题并非已执行政策。'))
    rows = [raw(), {**raw(), 'title': '央行公布新政策'}]
    baseline = capture(service, rows, request(request_key='mixed_analysis_00001'))
    other = next(e for e in baseline['events'] if e['verification'] != 'retracted')
    analyzer.is_available.return_value = True
    analyzer.generate_text.return_value = encode({'events': [interpretation(other)]})
    result = capture(service, rows, request(request_key='mixed_analysis_00002', analyze=True))
    blocked = next(e for e in result['events'] if e['verification'] == 'retracted')
    assert blocked['analysis_status'] == 'blocked_by_verification'
    assert blocked['analysis'] is None
    assert result['coverage']['analysis_status'] == 'available'


@pytest.mark.parametrize('archive_failed', [False, True])
def test_market_review_entry_appends_snapshot_without_extra_search(setup, monkeypatch, archive_failed):
    from src.market_analyzer import MarketAnalyzer
    service, _, model, search = setup
    review = object.__new__(MarketAnalyzer)
    review.region = 'cn'
    review.get_market_overview = Mock(return_value=SimpleNamespace(date='2026-09-29'))
    news = [SimpleNamespace(title='央行利率政策', snippet='仅为合成测试消息', source='test',
                           url='https://example.com/news', published_date='2026-09-29')]
    review.search_market_news = Mock(return_value=news)
    review._merge_persisted_market_intelligence = Mock(side_effect=lambda items: items)
    review.generate_market_review = Mock(return_value='Main review retained')
    review._get_review_language = Mock(return_value='zh')
    review._supports_market_light = Mock(return_value=False)
    review.build_market_review_payload = Mock(return_value={})
    if archive_failed:
        service.capture_report_news = Mock(side_effect=RuntimeError('archive unavailable'))
    monkeypatch.setattr('src.services.market_event_service.MarketEventService', lambda: service)
    result = review._run_daily_review_parts()
    assert result.report.startswith('Main review retained')
    if archive_failed:
        assert '归档失败' in result.report
        assert 'market_events' not in result.structured_payload
    else:
        assert '今日市场事件' in result.report
        assert result.structured_payload['market_events']['events'][0]['title'] == '央行利率政策'
        assert count(service.repo, MarketEventBrief) == 1
    review.search_market_news.assert_called_once()
    review.generate_market_review.assert_called_once()
    search.search_topic_news_bounded.assert_not_called()
    model.generate_text.assert_not_called()


def test_generation_lock_released_after_failure_and_busy_is_explicit(setup, monkeypatch):
    service, *_ = setup
    monkeypatch.setattr(endpoint, 'MarketEventService', lambda: service)
    app = FastAPI(); app.include_router(endpoint.router, prefix='/events')
    client = TestClient(app)
    endpoint._generation_lock.acquire()
    try:
        assert client.post('/events', json=request().model_dump()).status_code == 409
    finally:
        endpoint._generation_lock.release()
    service.generate = Mock(side_effect=RuntimeError('sensitive details'))
    result = client.post('/events', json=request().model_dump())
    assert result.status_code == 500
    assert 'sensitive details' not in result.text
    assert not endpoint._generation_lock.locked()
