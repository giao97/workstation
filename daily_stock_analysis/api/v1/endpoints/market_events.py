"""Market event briefs. No broker operations, signals, or notification scheduling."""
import logging
import threading
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from src.schemas.market_events import BriefRequest, VerificationRequest, AnalysisRetryRequest
from src.core.market_events import digest
from src.services.task_queue import get_task_queue
from src.services.market_event_service import MarketEventService

logger = logging.getLogger(__name__)
router = APIRouter()
_generation_lock = threading.Lock()
_submission_lock = threading.Lock()


def _job_id(key):
    return 'market_events_' + digest(key)


def _job_status(key, service):
    archived = service.repo.by_key(key)
    if archived:
        return {'status': 'completed', 'stage': 'archived', 'brief_id': archived['id']}
    task = get_task_queue().get_task(_job_id(key))
    if not task:
        return {'status': 'unknown', 'stage': 'unknown', 'brief_id': None}
    return {'status': task.status.value, 'stage': task.message if task.status.value == 'processing' else task.status.value,
            'brief_id': None}


def _submit(key, fingerprint, operation, market):
    service = MarketEventService()
    queue = get_task_queue()
    with _submission_lock:
        existing = service.repo.by_key(key)
        if existing:
            if existing['request_hash'] != fingerprint:
                raise HTTPException(400, detail={'error': 'request_key_conflict', 'message': 'Request key parameters changed'})
            return _job_status(key, service)
        task = queue.get_task(_job_id(key))
        if task:
            if task.trace_id != fingerprint:
                raise HTTPException(400, detail={'error': 'request_key_conflict', 'message': 'Request key parameters changed'})
            return _job_status(key, service)
        if not _generation_lock.acquire(blocking=False):
            raise HTTPException(409, detail={'error': 'generation_busy', 'message': 'A market brief is already being generated'})

        def run():
            try:
                stages = {'collecting': 20, 'selecting': 40, 'interpreting': 60, 'archiving': 90}
                service.progress = lambda stage: queue.update_task_progress(_job_id(key), stages[stage], stage)
                result = operation(service)
                return {'brief_id': result['id']}
            except Exception:
                # Generic task queue logs exception text; never forward provider URLs, keys or prompts.
                raise RuntimeError('market_event_job_failed') from None
            finally:
                _generation_lock.release()
        try:
            queue.submit_background_task(run, stock_code='MARKET_EVENTS', report_type='market_events',
                                         task_id=_job_id(key), trace_id=fingerprint, region=market)
        except Exception:
            _generation_lock.release()
            raise
    return _job_status(key, service)


def _call(operation):
    try:
        return operation(MarketEventService())
    except LookupError as exc:
        raise HTTPException(404, detail={'error': 'not_found', 'message': str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, detail={'error': 'invalid_market_event_request', 'message': str(exc)}) from exc
    except Exception as exc:
        logger.warning('Market event operation failed', exc_info=False)
        raise HTTPException(500, detail={'error': 'market_event_failed', 'message': 'Market event operation failed'}) from exc


@router.get('')
def list_briefs(market: Optional[Literal['cn', 'hk', 'us', 'global']] = None,
                limit: int = Query(30, ge=1, le=100)):
    return _call(lambda service: {'items': service.repo.list(market, limit)})


@router.post('')
def generate(request: BriefRequest):
    # A bounded, synchronous research operation; no background worker/scheduler.
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(409, detail={'error': 'generation_busy', 'message': 'A market brief is already being generated'})
    try:
        return _call(lambda service: service.generate(request))
    finally:
        _generation_lock.release()


@router.post('/jobs', status_code=202)
def start_generation(request: BriefRequest):
    return _submit(request.request_key, digest(request.model_dump(exclude={'request_key'})),
                   lambda service: service.generate(request), request.market)


@router.get('/jobs/{request_key}')
def job_status(request_key: str):
    # Same key validation as submission, even for read-only recovery requests.
    try:
        AnalysisRetryRequest(request_key=request_key)
    except ValueError as exc:
        raise HTTPException(400, detail='Invalid request key') from exc
    return _call(lambda service: _job_status(request_key, service))


@router.post('/{brief_id}/retry-analysis', status_code=202)
def retry_analysis(brief_id: int, request: AnalysisRetryRequest):
    parent = _call(lambda service: service.get(brief_id))
    return _submit(request.request_key, digest({'operation': 'retry_analysis', 'parent_id': brief_id}),
                   lambda service: service.retry_analysis(brief_id, request.request_key), parent['market'])


@router.get('/{brief_id}')
def get(brief_id: int):
    return _call(lambda service: service.get(brief_id))


@router.post('/{brief_id}/verifications')
def verify(brief_id: int, request: VerificationRequest):
    return _call(lambda service: service.verify(brief_id, request))
