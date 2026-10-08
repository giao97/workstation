"""Offline review journal integration: real temporary SQLite, no broker writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, text

from src.repositories.allocation_review_repo import AllocationReviewConflict, AllocationReviewRepository
from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
from src.schemas.allocation_review import AllocationReviewItem
from src.services.allocation_review_service import AllocationReviewService
from src.services.portfolio_allocation_service import PortfolioAllocationService
from src.services.portfolio_allocation_report import render_allocation_status
from src.storage import DatabaseManager

NOW = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)


@pytest.fixture
def setup_review(tmp_path, monkeypatch):
    monkeypatch.setenv('ENV_FILE', str(tmp_path / 'missing.env'))
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f'sqlite:///{tmp_path / "review.db"}')
    plans = PortfolioAllocationRepository(db)
    plan, _ = plans.create_plan(name='Synthetic allocation', owner_id=None, base_currency='CNY',
        target_total_value=100000, ledger_complete=True, targets=[dict(key='core', name='Core ETF',
        source='position', policy='buy_only', market='us', symbols=['VOO'], target_pct=100, batch_amount=1000)])
    service = AllocationReviewService(AllocationReviewRepository(db), clock=lambda: NOW)
    yield service, plans, plan.id, db
    DatabaseManager.reset_instance()


def request(**changes):
    return dict(dict(request_key='first', expected_plan_version=1, expected_previous_id=None,
        target_key='core', horizon='long_term', decision='maintain_plan', reason='Long-term allocation unchanged',
        evidence='Synthetic test evidence; no live quote', next_condition='Recheck available cash and valuation',
        review_due_at='2026-10-01T14:00:00+08:00'), **changes)


def test_independent_tracks_append_history_and_idempotency(setup_review):
    service, plans, plan_id, _ = setup_review
    original = plans.plan_to_dict(plans.get_plan(plan_id)[0])
    first = service.append(plan_id, request())
    assert AllocationReviewItem.model_validate(first).authority == 'manual_unverified'
    assert first['review_due_at'] == '2026-10-01T06:00:00Z'
    assert service.append(plan_id, request())['id'] == first['id']
    tactical = service.append(plan_id, request(request_key='tactical', horizon='tactical', decision='wait',
        reason='Intraday evidence missing'))
    second = service.append(plan_id, request(request_key='second', expected_previous_id=first['id'], decision='data_required'))
    assert second['revision'] == 2 and tactical['revision'] == 1
    assert second['target_snapshot']['batch_amount'] == 1000
    page = service.list(plan_id, 'core', limit=1)
    assert page['items'][0]['id'] == second['id']
    assert {item['id'] for item in page['latest']} == {second['id'], tactical['id']}
    older = service.list(plan_id, 'core', before_id=page['next_before_id'])
    assert [item['id'] for item in older['items']] == [tactical['id'], first['id']]
    assert older['next_before_id'] is None
    assert plans.plan_to_dict(plans.get_plan(plan_id)[0]) == original


def test_rejects_stale_writes_missing_conditions_and_extra_order_fields(setup_review):
    service, _, plan_id, _ = setup_review
    first = service.append(plan_id, request())
    for payload in [request(request_key='other'), request(reason='changed key reuse'),
                    request(request_key='wrong-version', expected_plan_version=2)]:
        with pytest.raises(AllocationReviewConflict):
            service.append(plan_id, payload)
    for change in [dict(reason='   '), dict(evidence=''), dict(next_condition=''), dict(quantity=1),
                   dict(review_due_at='2026-10-01T06:00:00'), dict(horizon='intraday')]:
        with pytest.raises(ValidationError):
            service.append(plan_id, request(**change))
    with pytest.raises(ValueError, match='future'):
        service.append(plan_id, request(request_key='past', review_due_at=NOW.isoformat(), expected_previous_id=first['id']))
    with pytest.raises(LookupError):
        service.append(plan_id, request(request_key='unknown-target', target_key='watchlist'))


def test_due_and_plan_change_never_renew_or_overwrite(setup_review):
    service, plans, plan_id, _ = setup_review
    first = service.append(plan_id, request())
    service.clock = lambda: NOW + timedelta(days=1)
    assert service.list(plan_id, 'core')['latest'][0]['state'] == 'due'
    assert service.append(plan_id, request())['id'] == first['id']  # retry after deadline remains idempotent
    plans.update_plan(plan_id=plan_id, name='Changed', owner_id=None, base_currency='CNY', target_total_value=200000,
        targets=[dict(key='core', name='New core', source='manual', policy='hold_only', target_pct=100)])
    item = service.latest(plan_id)[0]
    assert item['state'] == 'plan_changed' and item['target_snapshot']['name'] == 'Core ETF'
    assert service.list(plan_id, 'core')['items'][0]['reason'] == first['reason']
    plans.deactivate_plan(plan_id)
    assert service.latest(plan_id)[0]['state'] == 'plan_inactive'
    with pytest.raises(LookupError):
        service.append(plan_id, request(request_key='inactive', expected_previous_id=first['id'],
            expected_plan_version=2, review_due_at=(NOW + timedelta(days=2)).isoformat()))


def test_concurrent_review_head_is_not_lost(setup_review):
    service, _, plan_id, _ = setup_review
    def save(key):
        try:
            return service.append(plan_id, request(request_key=key))['id']
        except AllocationReviewConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ['one', 'two']))
    assert results.count('conflict') == 1
    assert len(service.list(plan_id, 'core')['items']) == 1


def test_concurrent_same_request_is_idempotent(setup_review):
    service, _, plan_id, _ = setup_review
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: service.append(plan_id, request())['id'], range(2)))
    assert ids[0] == ids[1]
    assert len(service.list(plan_id, 'core')['items']) == 1


def test_reviews_leave_all_financial_tables_and_caps_unchanged(setup_review):
    service, plans, plan_id, db = setup_review
    tables = [name for name in inspect(db._engine).get_table_names()
              if name.startswith('portfolio_') and name != 'portfolio_allocation_reviews']
    def ledger():
        with db.get_session() as session:
            return {name: [tuple(row) for row in session.execute(text(f'SELECT * FROM "{name}"'))] for name in tables}
    before = ledger()
    class Portfolio:
        def get_portfolio_snapshot(self, **kwargs):
            return dict(as_of=kwargs['as_of'].isoformat(), account_count=1, limitations=[], accounts=[
                dict(account_id=1, base_currency='CNY', total_cash=10000, positions=[])])
        def convert_amount(self, **kwargs):
            return kwargs['amount'], False, 'same_currency'
    allocation = PortfolioAllocationService(repo=plans, portfolio_service=Portfolio())
    initial = allocation.evaluate_plan(plan_id, include_realtime=False)
    first = service.append(plan_id, request(horizon='tactical', decision='wait', reason='Synthetic missing minute evidence'))
    after = allocation.evaluate_plan(plan_id, include_realtime=False)
    assert after['targets'][0]['research_reviews'][0]['id'] == first['id']
    for result in [initial, after]:
        for target in result['targets']:
            target.pop('research_reviews', None)
            # Daily research has its own evaluation timestamp, not ledger state.
            target.pop('core_entries', None)
    assert initial == after and ledger() == before
    historical = allocation.evaluate_plan(plan_id, as_of=date(2020, 1, 1), include_realtime=False)
    assert not historical['targets'][0].get('research_reviews')


def test_api_conflicts_and_reports_use_same_record(setup_review):
    from api.v1.endpoints.portfolio import router
    service, _, plan_id, _ = setup_review
    app = FastAPI(); app.include_router(router, prefix='/portfolio')
    with TestClient(app) as client, patch('api.v1.endpoints.portfolio.AllocationReviewService', return_value=service):
        url = f'/portfolio/allocation-plans/{plan_id}/reviews'
        response = client.post(url, json=request())
        assert response.status_code == 200, response.text
        assert client.post(url, json=request()).json()['id'] == response.json()['id']
        assert client.post(url, json=request(request_key='stale')).status_code == 409
        assert client.post(url, json=request(evidence='')).status_code == 422
        assert client.get(url, params={'target_key': 'core', 'limit': 0}).status_code == 422
        assert client.get('/portfolio/allocation-plans/999/reviews', params={'target_key': 'core'}).status_code == 404
        latest = client.get(url, params={'target_key': 'core'}).json()['latest']
    from tests.test_portfolio_allocation_report import _status
    status = _status(); status['targets'][0]['research_reviews'] = latest
    zh, en = render_allocation_status(status), render_allocation_status(status, language='en')
    assert '长期配置 / 短线复核' in zh and '不修改长期目标或共享预算' in zh
    assert 'manual record, not a live signal' in en and latest[0]['evidence'] in en
    latest[0]['evidence'] = '![not-an-image](https://example.com/x) <script>bad</script>'
    markdown = render_allocation_status(status)
    assert '![not-an-image]' not in markdown and '<script>' not in markdown
