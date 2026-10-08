"""Deterministic retry/archive and real shared-queue integration checks."""
from datetime import timedelta
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import market_events as endpoint
from src.core.market_events import encode
from src.schemas.market_events import VerificationRequest
from src.services.task_queue import AnalysisTaskQueue
from tests.test_market_events import setup, capture, request, raw, interpretation, NOW  # noqa: F401


def test_retry_only_missing_frozen_inputs_idempotent(setup):
    service, clock, model, _ = setup
    rows = [raw(), {**raw(), 'title': '央行利率政策观察', 'url': 'https://example.com/rates'}]
    seed = capture(service, rows)
    assert len(seed['events']) == 2
    model.is_available.return_value = True
    model.generate_text.return_value = encode({'events': [interpretation(seed['events'][0])]})
    parent = capture(service, rows, request(request_key='partial_parent_0001', analyze=True))
    before = encode(service.repo.get(parent['id']))
    assert parent['coverage']['analysis_failure'] == 'model_omitted_events'
    clock.return_value = NOW + timedelta(days=1)
    service._collect = lambda _: pytest.fail('Retry must not recollect')
    service.holdings_loader = lambda _: pytest.fail('Retry must not refresh holdings')
    model.generate_text.return_value = encode({'events': [interpretation(parent['events'][1])]})
    stages = []
    service.progress = stages.append
    retry = service.retry_analysis(parent['id'], 'retry_partial_00001')
    assert stages == ['interpreting', 'archiving']
    assert retry['coverage']['analysis_status'] == 'available'
    assert retry['coverage']['analysis_failure'] is None
    assert retry['captured_at'] == parent['captured_at']
    assert retry['analysis_retried_at'] != parent['captured_at']
    assert retry['parent_brief_id'] == parent['id']
    assert retry['events'][0] == parent['events'][0]
    assert retry['events'][1]['evidence'] == parent['events'][1]['evidence']
    assert parent['events'][0]['event_key'] not in model.generate_text.call_args.args[0]
    assert encode(service.repo.get(parent['id'])) == before
    calls = model.generate_text.call_count
    assert service.retry_analysis(parent['id'], 'retry_partial_00001')['id'] == retry['id']
    assert model.generate_text.call_count == calls
    with pytest.raises(ValueError):
        service.retry_analysis(seed['id'], 'retry_partial_00001')
    with pytest.raises(ValueError, match='No eligible'):
        service.retry_analysis(retry['id'], 'retry_complete_0001')


def test_retracted_missing_interpretations_not_retried(setup):
    service, _, model, _ = setup
    parent = capture(service)
    service.verify(parent['id'], VerificationRequest(event_key=parent['events'][0]['event_key'],
        status='retracted', evidence_url='https://example.com/correction', note='Original claim was withdrawn'))
    with pytest.raises(ValueError, match='No eligible'):
        service.retry_analysis(parent['id'], 'retry_retracted_001')
    model.generate_text.assert_not_called()


@pytest.mark.parametrize('output,reason', [('', 'model_empty'), ('bad json', 'model_contract_invalid'),
    ('{"events": []}', 'model_omitted_events')])
def test_failure_reason_and_reset(setup, output, reason):
    service, _, model, _ = setup
    model.is_available.return_value = True
    model.generate_text.return_value = output
    failed = capture(service, req=request(analyze=True))
    assert failed['coverage']['analysis_failure'] == reason
    untouched = capture(service, req=request(request_key='without_model_00001'))
    assert untouched['coverage']['analysis_failure'] is None


def test_timeout_keeps_evidence(setup):
    service, _, model, _ = setup
    model.is_available.return_value = True
    model.generate_text.side_effect = TimeoutError('secret provider URL')
    result = capture(service, req=request(analyze=True))
    assert result['events'][0]['evidence']
    assert result['coverage']['analysis_failure'] == 'model_timeout'
    assert 'secret' not in encode(result)


@pytest.fixture()
def queued(setup, monkeypatch):
    service, *_ = setup
    monkeypatch.setattr(AnalysisTaskQueue, '_instance', None)
    queue = AnalysisTaskQueue(max_workers=1)
    monkeypatch.setattr(endpoint, 'MarketEventService', lambda: service)
    monkeypatch.setattr(endpoint, 'get_task_queue', lambda: queue)
    app = FastAPI()
    app.include_router(endpoint.router, prefix='/events')
    yield TestClient(app), service, queue
    queue.shutdown()


def terminal(client, key):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = client.get('/events/jobs/' + key).json()
        if result['status'] in {'completed', 'failed'}:
            return result
        sleep(.01)
    pytest.fail('Job did not terminate')


def test_real_queue_progress_dedupe_conflict_and_recovery(queued):
    client, service, queue = queued
    entered, release = Event(), Event()
    calls = []
    def collect(req):
        calls.append(req)
        entered.set()
        assert release.wait(5)
        return [raw()], [{'source': 'fixture', 'status': 'ok'}]
    service._collect = collect
    body = request().model_dump()
    key = body['request_key']
    try:
        assert client.post('/events/jobs', json=body).status_code == 202
        assert entered.wait(2)
        progress = client.get('/events/jobs/' + key).json()
        assert progress['stage'] == 'collecting'
        assert client.post('/events/jobs', json=body).status_code == 202
        assert len(calls) == 1
        assert client.post('/events/jobs', json={**body, 'analyze': True}).status_code == 400
        assert client.post('/events/jobs', json={**body, 'request_key': 'another_job_key_0001'}).status_code == 409
    finally:
        release.set()
    result = terminal(client, key)
    assert result['status'] == 'completed'
    assert result['brief_id']
    assert client.get('/events/' + str(result['brief_id'])).status_code == 200
    # Completed jobs are recoverable from durable archives without queue memory.
    with queue._data_lock:
        queue._tasks.clear()
    assert client.get('/events/jobs/' + key).json() == result
    assert client.post('/events/jobs', json=body).json() == result
    assert len(calls) == 1
    assert client.get('/events/jobs/unknown_request_001').json()['status'] == 'unknown'


def test_job_failure_is_sanitized_and_lock_released(queued):
    client, service, _ = queued
    def fail(_):
        raise RuntimeError('secret credential')
    service._collect = fail
    body = request().model_dump()
    client.post('/events/jobs', json=body)
    failed = terminal(client, body['request_key'])
    assert failed['status'] == 'failed'
    assert 'secret' not in encode(failed)
    service._collect = lambda _: ([raw()], [])
    body['request_key'] = 'after_failed_job_001'
    assert client.post('/events/jobs', json=body).status_code == 202
    assert terminal(client, body['request_key'])['status'] == 'completed'


def test_retry_api_archives_gap_and_preserves_parent(queued):
    client, service, _ = queued
    parent = capture(service)
    body = {'request_key': 'retry_api_request_001'}
    response = client.post(f"/events/{parent['id']}/retry-analysis", json=body)
    assert response.status_code == 202
    job = terminal(client, body['request_key'])
    assert job['status'] == 'completed'  # archived does not mean model succeeded
    revision = client.get('/events/' + str(job['brief_id'])).json()
    assert revision['coverage']['analysis_failure'] == 'model_unavailable'
    assert revision['parent_brief_id'] == parent['id']
    assert revision['captured_at'] == parent['captured_at']
    assert service.repo.get(parent['id'])['coverage']['analysis_status'] == 'not_requested'
    assert client.post(f"/events/{parent['id']}/retry-analysis", json=body).json() == job
