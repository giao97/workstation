from src.core.sector_research import sector_ids, sector_queries, sector_radar


def event(**patch):
    return {'event_key': 'test', 'verification': 'reported', 'time_bucket': 'today',
            'evidence': [{'title': 'US cybersecurity earnings', 'summary': 'New contracts'}], **patch}


def test_ai_apps_and_cyber_not_only_semiconductors():
    assert sector_ids('Enterprise software AI applications cybersecurity') == ['ai_apps', 'cybersecurity']
    assert sector_ids('turmoil retailing goldfish') == []
    assert len(sector_queries('us')) == 3
    assert len(sector_queries('cn')) == 5


def test_radar_missing_evidence_is_not_no_opportunity_or_holdings():
    radar = sector_radar([event()])
    cyber = next(r for r in radar if r['sector'] == 'cybersecurity')
    assert cyber['state'] == 'evidence_watch' and cyber['executable'] is False
    assert next(r for r in radar if r['sector'] == 'healthcare')['state'] == 'no_selected_evidence'


def test_retractions_and_unknown_time_remove_candidate_status():
    for row in [event(time_bucket='time_unknown'), event(verification='unverified'), event(time_bucket='date_only')]:
        cyber = next(r for r in sector_radar([row]) if r['sector'] == 'cybersecurity')
        assert cyber['state'] == 'verification_required' and not cyber['eligible_event_keys']
    reviewed = sector_radar([event()], [{'event_key': 'test', 'status': 'retracted'}])
    assert next(r for r in reviewed if r['sector'] == 'cybersecurity')['state'] == 'verification_required'


def test_battery_theme_and_late_arriving_news_are_not_hidden():
    from src.core.sector_research import diverse_news
    assert 'batteries' in sector_ids('A股固态电池储能逆势涨停')
    macro = [{'title': f'央行新闻{i}'} for i in range(15)]
    battery = {'title': '固态电池订单', 'url': 'https://example.com/battery'}
    assert battery in diverse_news(macro + [battery], limit=6)
    assert len(diverse_news(macro + [battery, battery], limit=6)) == 6


def test_coverage_audit_never_infers_trades_or_reconstructs_legacy_baseline():
    from src.core.sector_research import coverage_audit
    battery = event(evidence=[{'title': '固态电池', 'summary': '订单'}])
    previous = {'id': 1, 'captured_at': '2026-10-08T01:13:00Z', 'events': [], 'candidate_events': [battery]}
    def state(prior):
        return next(r['state'] for r in coverage_audit([battery], prior)['rows'] if r['sector'] == 'batteries')
    assert state(previous) == 'previously_collected_not_selected'
    assert state({**previous, 'events': [battery]}) == 'previously_selected'
    assert state({**previous, 'candidate_events': []}) == 'newly_observed'
    assert state(None) == 'no_baseline'
    assert state({'id': 2, 'events': [battery]}) == 'no_baseline'
