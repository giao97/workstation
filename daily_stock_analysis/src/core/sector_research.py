"""Cross-sector news coverage, not price signals or a holdings universe."""
import re

SECTORS = {
    'ai_apps': ('AI 应用 / 企业软件', 'AI applications / software', ('ai application', 'enterprise software', 'saas', 'ai agent', 'AI应用', '企业软件', '智能体')),
    'cybersecurity': ('网络安全', 'Cybersecurity', ('cybersecurity', 'cyber security', 'ransomware', '网络安全', '勒索软件')),
    'semiconductors': ('半导体 / AI 基建', 'Semiconductors / AI infrastructure', ('semiconductor', 'chip', 'memory', 'hbm', 'data center', '半导体', '存储', '芯片', '算力')),
    'power': ('电力 / 电网', 'Power / grid', ('power grid', 'electricity', 'utilities', '电力', '电网')),
    'batteries': ('电池 / 固态电池 / 储能', 'Batteries / solid-state / storage', ('battery', 'batteries', 'solid-state', 'energy storage', '电池', '储能', '锂电', '钠电')),
    'transport': ('航运 / 交通', 'Shipping / transport', ('shipping', 'tanker', 'freight', '航运', '港口', '运价')),
    'industrials': ('工业 / 自动化', 'Industrials / automation', ('industrial', 'automation', 'robotics', '工业', '自动化', '机器人')),
    'healthcare': ('医疗', 'Healthcare', ('healthcare', 'biotech', 'clinical', '医疗', '生物科技', '临床')),
    'consumer': ('消费', 'Consumer', ('retail', 'consumer spending', '消费', '零售')),
    'financials': ('金融', 'Financials', ('bank', 'banks', 'insurance', '银行', '保险')),
    'energy_gold': ('能源 / 黄金', 'Energy / gold', ('oil', 'energy', 'gold', '原油', '能源', '黄金')),
}


def sector_ids(content):
    return [key for key, (_, _, terms) in SECTORS.items() if any(
        re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', content, re.I)
        if term.isascii() else term.lower() in content.lower() for term in terms)]


def sector_queries(market):
    """Bounded discovery, including market-led themes outside the fixed taxonomy."""
    if market in {'cn', 'hk'}:
        return ['AI应用 企业软件 网络安全 半导体 业绩 订单',
                '电池 固态电池 储能 锂电 订单 产能 政策',
                '电力 电网 工业 自动化 航运 运价',
                '医疗 消费 银行 能源 黄金 业绩',
                '市场热点 板块轮动 逆势 涨停梯队 节前强势 假期催化']
    return ['US AI applications enterprise software cybersecurity earnings contracts',
            'US power grid battery energy storage industrial automation orders earnings',
            'US healthcare consumer banks energy gold earnings outlook']


def diverse_news(news, limit=12):
    """Keep late-arriving sector leads in bounded prompts; not a quality score."""
    first, repeated, seen_titles, seen_sectors = [], [], set(), set()
    for item in news:
        get = item.get if isinstance(item, dict) else lambda key, default='': getattr(item, key, default)
        title = str(get('title') or '')
        identity = re.sub(r'\s+', '', title).casefold()
        if identity in seen_titles:
            continue
        seen_titles.add(identity)
        sectors = set(sector_ids(title + ' ' + str(get('snippet') or get('summary') or '')))
        bucket = sectors or {'general'}
        (first if bucket - seen_sectors else repeated).append(item)
        seen_sectors.update(bucket)
    return (first + repeated)[:limit]


def coverage_audit(current, previous):
    """Compare frozen news coverage, never infer a trade trigger or missed profit."""
    baseline = previous if previous and 'candidate_events' in previous else None
    prior_pool = {r['sector']: r for r in sector_radar(baseline['candidate_events'])} if baseline else {}
    prior_selected = {r['sector']: r for r in sector_radar(baseline['events'])} if baseline else {}
    rows = []
    for row in sector_radar(current):
        key = row['sector']
        state = ('no_baseline' if not baseline else
                 'not_observed_now' if not row['event_keys'] else
                 'previously_selected' if prior_selected[key]['event_keys'] else
                 'previously_collected_not_selected' if prior_pool[key]['event_keys'] else
                 'newly_observed')
        rows.append({'sector': key, 'label_zh': row['label_zh'], 'label_en': row['label_en'], 'state': state})
    return {'baseline_id': baseline['id'] if baseline else None,
            'baseline_at': baseline['captured_at'] if baseline else None,
            'scope': 'same_day_news_coverage_not_trade_performance', 'rows': rows}


def sector_radar(events, reviews=()):
    latest = {v['event_key']: v['status'] for v in reviews}
    rows = []
    for key, (zh, en, _) in SECTORS.items():
        matched = [e for e in events if key in sector_ids(' '.join(
            v['title'] + ' ' + v['summary'] for v in e['evidence']))]
        usable = [e for e in matched if latest.get(e['event_key'], e['verification']) not in
                  {'disputed', 'retracted', 'unverified'} and e['time_bucket'] in {'today', 'carryover'}]
        rows.append({'sector': key, 'label_zh': zh, 'label_en': en,
                     'state': 'evidence_watch' if usable else 'verification_required' if matched else 'no_selected_evidence',
                     'event_keys': [e['event_key'] for e in matched],
                     'eligible_event_keys': [e['event_key'] for e in usable],
                     'executable': False})
    return rows
