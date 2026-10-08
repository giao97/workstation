"""Conservative news evidence normalization and ranking. No trading signals."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
from src.core.sector_research import SECTORS, sector_ids, sector_radar

VERSION = 'market-events-v4'
ZONES = {'cn': 'Asia/Shanghai', 'hk': 'Asia/Hong_Kong', 'us': 'America/New_York', 'global': 'UTC'}
PRIMARY_DOMAINS = ('gov.cn', 'bls.gov', 'bea.gov', 'federalreserve.gov', 'sec.gov',
                   'rba.gov.au', 'sse.com.cn', 'szse.cn', 'hkexnews.hk',
                   'nvidianews.nvidia.com', 'investors.micron.com')
TOPICS = {
    'macro': ('央行', '财政', '国务院', '利率', '降息', '加息', '通胀', '非农', '收益率', '消费者信心', '职位空缺',
              'cpi', 'federal reserve', 'fed', 'inflation', 'jolts', 'treasury', 'bond yields', 'interest rate', 'rate decision', 'consumer confidence', 'payrolls'),
    'geopolitics': ('关税', '制裁', '战争', '停火', '原油', '石油', '霍尔木兹', '能源供应', '能源运输',
                    'tariff', 'sanction', 'oil', 'ceasefire', 'hormuz', 'energy supply'),
    'technology': ('半导体', '存储', '芯片', '算力', '英伟达', '光刻', '台积电', '美光', 'chip', 'chip-making',
                   'semiconductor', 'nvidia', 'memory', 'micron', 'tsmc', 'ai', 'hbm'),
    'property': ('房地产', '购房', '房贷', '住房', 'mortgage', 'housing'),
    'company': ('财报', '回购', '分红', '业绩', '并购', '评级', '目标价', '盘前', '临床', 'earnings', 'buyback',
                'repurchase', 'dividend', 'acquisition', 'licensing', 'guidance', 'stock', 'stocks', 's&p'),
}
MARKET_TERMS = {
    'us': ('美国', '美股', '美联储', '美债', '标普', '纳指', '纳斯达克', '道琼斯', '英伟达', '美光', '台积电',
           '礼来', '奈飞', '华尔街', 'nasdaq', 's&p', 'dow jones', 'federal reserve', 'treasury', 'jolts',
           'nvidia', 'micron', 'tsmc', 'fed', 'u.s.', 'united states', 'wall street'),
    'cn': ('中国', '财政部', '国务院', 'a股', '沪深', '中证', '人民银行', 'a-share', 'china', 'pboc'),
    'hk': ('香港', '港股', '港元', '恒生', '金管局', 'hong kong', 'hang seng', 'hkma'),
}
GLOBAL_TRANSMISSION_TERMS = ('原油', '石油', '霍尔木兹', '能源供应', '能源运输', '全球长期利率', '关税',
                             'oil', 'hormuz', 'energy supply', 'tariff', 'global bond yields', 'ai build-out', 'ai infrastructure')
TOPIC_LIMITS = {'geopolitics': 2, 'macro': 3, 'technology': 3, 'company': 3, 'property': 2}
TOPIC_LIMITS.update({key: 2 for key in SECTORS})


def contains_term(content, terms):
    """English words must not match inside unrelated words (oil != turmoil)."""
    return any(re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', content, re.I)
               if re.search('[a-z]', term, re.I) else term in content for term in terms)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def text(value, limit=1600):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', str(value or ''))).strip()[:limit]


def safe_url(value):
    """Links only. This module never dereferences arbitrary model/user URLs."""
    try:
        parsed = urlsplit(str(value or '').strip())
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.scheme not in {'https', 'http'} or not host or parsed.username or parsed.password:
            return ''
        if host == 'localhost' or host.endswith(('.local', '.internal')) or '.' not in host:
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            pass
        query = [(k, v) for k, v in parse_qsl(parsed.query)
                 if not re.search(r'utm_|token|secret|password|api.?key|signature|credential', k, re.I)]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))[:2000]
    except ValueError:
        return ''


def publication(value):
    """Never infer a timezone for date-only or naive legacy timestamps."""
    raw = str(value or '').strip()
    if not raw:
        return None, 'unknown'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        try:
            datetime.strptime(raw, '%Y-%m-%d')
            return raw, 'date_only'
        except ValueError:
            return None, 'unknown'
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            dt = datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, timezone.utc)
        else:
            try:
                dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except ValueError:
                dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None, 'timezone_unknown'
        return dt.astimezone(timezone.utc).isoformat(), 'timestamp'
    except (ValueError, TypeError, OverflowError, OSError):
        return None, 'unknown'


def normalize_evidence(raw, now):
    title = text(raw.get('title'), 300)
    if not title:
        return None
    url = safe_url(raw.get('url'))
    published_raw = raw.get('published_at_raw', raw.get('published_at', raw.get('published_date')))
    published, precision = publication(published_raw)
    host = (urlsplit(url).hostname or '').lower()
    primary = any(host == d or host.endswith('.' + d) for d in PRIMARY_DOMAINS)
    event_at, event_precision = publication(raw.get('event_at'))
    payload = {
        'title': title, 'summary': text(raw.get('summary') or raw.get('snippet')),
        'url': url, 'source': text(raw.get('source') or raw.get('source_name') or 'unknown', 100),
        'published_at': published, 'published_at_raw': text(published_raw, 100), 'time_precision': precision,
        'event_at': event_at if event_precision == 'timestamp' else None,
        'market': raw.get('market') if raw.get('market') in ZONES else 'global',
        'source_tier': 'primary_link' if primary else ('reported' if url else 'unverified'),
    }
    # Identity excludes collection time. Changes to content create a new version.
    payload['evidence_id'] = digest(payload)
    payload['retrieved_at'] = now.isoformat()
    return payload


def time_bucket(evidence, now, zone):
    value, precision = evidence['published_at'], evidence['time_precision']
    today = now.astimezone(ZoneInfo(zone)).date()
    # Publication and scheduled occurrence are independent. An old notice can
    # describe a near-future event; a future publication is still quarantined.
    if precision == 'timestamp' and datetime.fromisoformat(value) > now:
        return 'future_publication'
    if precision == 'date_only' and datetime.strptime(value, '%Y-%m-%d').date() > today:
        return 'future_publication'
    event_at = evidence.get('event_at')
    if event_at and timedelta(0) < datetime.fromisoformat(event_at) - now <= timedelta(days=7):
        return 'upcoming_event'
    if precision == 'timestamp':
        dt = datetime.fromisoformat(value)
        if dt > now:
            return 'future_publication'
        if now - dt > timedelta(hours=48):
            return 'old'
        return 'today' if dt.astimezone(ZoneInfo(zone)).date() == today else 'carryover'
    if precision == 'date_only':
        day = datetime.strptime(value, '%Y-%m-%d').date()
        if day > today:
            return 'future_publication'
        return 'date_only' if (today - day).days <= 2 else 'old'
    return 'time_unknown'


def build_events(evidence, now, market, holdings=(), limit=8):
    """Only exact normalized titles+publication date merge across URLs.

    Different titles at one URL remain separate versions (e.g. a correction).
    Ranking is a transparent triage heuristic, never a probability of returns.
    """
    groups = {}
    excluded = {'old': 0, 'future_publication': 0, 'unmatched_topic': 0, 'unmatched_market': 0}
    for item in evidence:
        bucket = time_bucket(item, now, ZONES[market])
        if bucket in excluded:
            excluded[bucket] += 1
            continue
        title_key = re.sub(r'\s+', '', item['title']).casefold()
        # Do not merge date-unknown articles from unrelated collection days.
        day = (item['published_at'] or item['first_seen_at'])[:10]
        key = (title_key, day, item.get('event_at'))
        group = groups.setdefault(key, {'evidence': [], 'time_bucket': bucket})
        if item['evidence_id'] not in {e['evidence_id'] for e in group['evidence']}:
            group['evidence'].append(item)
    result = []
    for group in groups.values():
        items = group['evidence']
        title = items[0]['title']
        content = (' '.join(i['title'] + ' ' + i['summary'] for i in items)).lower()
        topics = [name for name, words in TOPICS.items() if contains_term(content, words)]
        sectors = sector_ids(content)
        topics.extend(sectors)
        mentioned = [h for h in holdings if re.search(r'(?<![a-z0-9])' + re.escape(h['symbol']) + r'(?![a-z0-9])', content, re.I)]
        if not topics and not mentioned:
            excluded['unmatched_topic'] += 1
            continue
        explicit = contains_term(content, MARKET_TERMS.get(market, ()))
        transmission = contains_term(content, GLOBAL_TRANSMISSION_TERMS)
        source_market = any(i['market'] == market for i in items)
        relevance = ('holding_mention' if mentioned else 'explicit_market' if explicit else
                     'global_transmission' if transmission else 'source_market' if source_market else
                     'global_scope' if market == 'global' else 'unmatched_market')
        if relevance == 'unmatched_market':
            excluded['unmatched_market'] += 1
            continue
        score = {'holding_mention': 8, 'explicit_market': 6, 'global_transmission': 3,
                 'source_market': 2, 'global_scope': 1}[relevance]
        score += 2 if group['time_bucket'] == 'upcoming_event' else 1 if group['time_bucket'] == 'today' else 0
        score += 2 if any(i['source_tier'] == 'primary_link' for i in items) else 0
        # Cap reading slots, not underlying risk or truth. Do not merge different
        # claims merely because they share a topic; retain every evidence version.
        primary_topic = next((t for t in ('company', 'technology', 'macro', 'geopolitics', 'property') if t in topics), 'company')
        if sectors:
            primary_topic = sectors[0]
        result.append({
            'event_key': digest(sorted(i['evidence_id'] for i in items)), 'title': title,
            'evidence_ids': [i['evidence_id'] for i in items], 'evidence': items,
            'time_bucket': group['time_bucket'], 'topics': topics,
            'priority_score': score, 'priority_basis': 'market relevance + literal symbol match (identity unverified) + occurrence/recency + primary link + topic cap',
            'market_relevance': relevance, 'primary_topic': primary_topic,
            'verification': 'reported' if all(i['url'] for i in items) else 'unverified',
            'analysis': None, 'analysis_status': 'not_requested',
            'direct_mentions': [{'symbol': h['symbol'], 'market': h['market']} for h in mentioned],
        })
    result.sort(key=lambda event: (event['priority_score'], max(i['published_at'] or '' for i in event['evidence'])), reverse=True)
    selected, topic_counts = [], {}
    # One reading slot per topic first, then fill remaining slots by evidence rank.
    first, repeated, seen_topics = [], [], set()
    for event in result:
        (repeated if event['primary_topic'] in seen_topics else first).append(event)
        seen_topics.add(event['primary_topic'])
    result = first + repeated
    for event in result:
        topic = event['primary_topic']
        if topic_counts.get(topic, 0) >= TOPIC_LIMITS[topic]:
            continue
        selected.append(event)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        if len(selected) >= limit:
            break
    return selected, {'excluded': excluded, 'candidate_count': len(result), 'not_selected': len(result) - len(selected),
                      'selection_rule': VERSION, 'topic_limits': TOPIC_LIMITS, 'candidate_events': result}


def render_brief(brief, language='zh'):
    """Deterministic report section; source text cannot create Markdown links."""
    zh = language == 'zh'
    def plain(value):
        return re.sub(r'[\[\]<>`*_#\\]', '', text(value, 700))
    title = '今日市场事件（新闻研究，非交易信号）' if zh else 'Market events (research, not trade signals)'
    lines = [f'### {title}', f"{brief['captured_at']} · {brief['timezone']} · {brief['coverage']['status']}"]
    lines.append('仅覆盖已取得的来源；报道不等于独立核验。' if zh else 'Available sources only; a report is not independent verification.')
    lines.append(f"{'模型解读状态' if zh else 'Model interpretation'}: {brief['coverage']['analysis_status']}")
    if brief.get('parent_brief_id'):
        lines.append(f"{'补充解读，沿用旧证据；原简报' if zh else 'Interpretation retry on old evidence; parent'}: "
                     f"#{brief['parent_brief_id']} · {brief['analysis_retried_at']}")
    if brief['coverage'].get('analysis_failure'):
        lines.append(f"{'解读缺口原因' if zh else 'Interpretation gap'}: {brief['coverage']['analysis_failure']}")
    if 'holding_status' in brief:
        basis = brief['holding_status']
        basis_zh = {'profile_reference': '投资档案参考（非交易账本）', 'profile_stale': '档案过期，暂停关联',
                    'profile_invalid': '档案格式或日期异常，暂停关联', 'profile_unavailable': '档案无法读取，暂停关联',
                    'recorded_ledger': '已记录账本', 'no_recorded_holdings': '未读取到持仓，不代表空仓', 'unavailable': '读取失败'}
        lines.append(f"{'持仓关联口径（非券商同步）' if zh else 'Holding basis (not broker sync)'}: "
                     f"{plain(basis_zh.get(basis, basis) if zh else basis.replace('_', ' '))}")
        profile_date = brief.get('holding_context', {}).get('profile_date')
        if profile_date:
            lines.append(f"{'档案版本日期（非成交/估值日期）' if zh else 'Profile version date (not trade/valuation time)'}: {plain(profile_date)}")
        lines.append(f"{'本期关联范围' if zh else 'Holding context'}: " + (' / '.join(
            f"{plain(h['symbol'])} ({plain(h['market'])})" for h in brief.get('holdings', [])) or '—'))
    for item in brief['events'][:8]:
        lines.append(f"- {plain(item['title'])} [{item['verification']} / {item['time_bucket']}]")
        for ev in item['evidence'][:2]:
            if ev['url']:
                # Angle-bracket destinations protect parentheses in source URLs.
                link = ev['url'].replace('<', '%3C').replace('>', '%3E').replace(' ', '%20')
                lines.append(f"  - {plain(ev['source'])}: [source](<{link}>) · {ev['published_at'] or 'time unknown'}")
        if item.get('analysis') and item['verification'] not in {'retracted', 'disputed'}:
            label = 'AI 条件式推演' if zh else 'AI conditional interpretation'
            analysis = item['analysis']
            lines.append(f"  - {label}: {plain(analysis['transmission'])}")
            lines.append(f"  - {'反向风险' if zh else 'Countercase'}: {plain(analysis['countercase'])}")
            lines.append(f"  - {'验证条件' if zh else 'Confirm'}: {plain(analysis['confirmation'])}")
            for holding in analysis.get('holding_links', []):
                lines.append(f"  - {'持仓可能关联（推演）' if zh else 'Potential holding link (inference)'}: "
                             f"{plain(holding['symbol'])} ({plain(holding['market'])}) · {plain(holding['reason'])}")
    if not brief['events']:
        lines.append('暂无足够证据，不代表市场没有重大消息。' if zh else 'Insufficient evidence; this does not mean there are no material events.')
    lines.append('\n#### ' + ('跨行业研究覆盖（非买入信号）' if zh else 'Cross-sector research coverage (not buy signals)'))
    labels = {'evidence_watch': ('有新闻线索，待核验估值与量价', 'News leads; verify valuation and price/volume'),
              'verification_required': ('先核验消息与时点', 'Verify claims and timing first'),
              'no_selected_evidence': ('本期选中材料未覆盖，不代表无机会', 'Not covered by selected evidence; not absence of opportunity')}
    for row in sector_radar(brief.get('candidate_events', brief['events']), brief.get('verification_history', [])):
        lines.append(f"- {row['label_zh' if zh else 'label_en']}: {labels[row['state']][0 if zh else 1]}")
    audit = brief.get('coverage_audit')
    if audit:
        lines.append('\n#### ' + ('覆盖复盘（非交易绩效）' if zh else 'Coverage audit (not trading performance)'))
        lines.append(f"{'同日基线快照' if zh else 'Same-day baseline'}: {audit['baseline_id'] or '—'}")
        names = {'no_baseline': '无可比基线', 'not_observed_now': '本期未取得线索',
                 'previously_selected': '此前已入选新闻（不等于建议买入）',
                 'previously_collected_not_selected': '此前收集到但未入选', 'newly_observed': '本次新发现（不证明此前可买）'}
        for row in audit['rows']:
            lines.append(f"- {row['label_zh' if zh else 'label_en']}: {names[row['state']] if zh else row['state']}")
    return '\n'.join(lines)
