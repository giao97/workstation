"""Independent paper observations. Never creates real orders or executions."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie
from pydantic import BaseModel, ConfigDict, Field

from src.auth import COOKIE_NAME
from src.core.paper_observation import ENGINE_VERSION, PaperAssumptions
from src.core.paper_minute import MinuteRules
from src.services.decision_signal_service import DecisionSignalNotFoundError
from src.services.paper_observation_service import PaperObservationService

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Security(APIKeyCookie(name=COOKIE_NAME, scheme_name="AdminSessionCookie", auto_error=False))])


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: int = Field(gt=0)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    assumptions: PaperAssumptions
    minute_rules: Optional[MinuteRules] = None


def _call(operation):
    try:
        return operation(PaperObservationService())
    except (LookupError, DecisionSignalNotFoundError) as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "Paper experiment or source signal not found"}) from exc
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "invalid_paper_request", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Paper observation failed")
        raise HTTPException(500, detail={"error": "paper_observation_failed", "message": "Paper observation failed"}) from exc


@router.post("")
def capture(request: CaptureRequest):
    return _call(lambda service: service.capture(request.signal_id, request.request_key, request.assumptions.model_dump(),
                                               request.minute_rules.model_dump(mode="json") if request.minute_rules else None))


@router.get("")
def list_experiments(signal_id: Optional[int] = Query(None, gt=0), limit: int = Query(50, ge=1, le=100)):
    return _call(lambda service: {"items": service.repo.list(signal_id, limit)})


@router.post("/{experiment_id}/evaluate")
def evaluate(experiment_id: int):
    return _call(lambda service: service.evaluate(experiment_id))


@router.get("/{experiment_id}/evidence/{horizon}")
def evidence(experiment_id: int, horizon: int):
    def read(service):
        experiment = service.get(experiment_id)
        engine = experiment["snapshot"].get("paper_policy_version", ENGINE_VERSION)
        item = service.repo.evidence(experiment_id, horizon, engine)
        if item is None:
            raise LookupError("paper_evidence_not_found")
        return item
    return _call(read)
