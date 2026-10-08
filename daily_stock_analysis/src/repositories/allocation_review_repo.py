"""Append-only allocation reviews with per-track optimistic concurrency."""
import json

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
from src.storage import DatabaseManager, PortfolioAllocationPlan, PortfolioAllocationReview, PortfolioAllocationTarget


class AllocationReviewConflict(ValueError):
    pass


class AllocationReviewRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    @staticmethod
    def decode(row):
        return dict(json.loads(row.payload_json), id=row.id, plan_id=row.plan_id, revision=row.revision) if row else None

    def by_request(self, plan_id, key):
        with self.db.get_session() as session:
            return self.decode(session.scalar(select(PortfolioAllocationReview).where(
                PortfolioAllocationReview.plan_id == plan_id, PortfolioAllocationReview.request_key == key)))

    @staticmethod
    def check_retry(existing, request):
        if any(existing.get(key) != value for key, value in request.items()):
            raise AllocationReviewConflict("Request key already belongs to a different review")
        return existing

    def append(self, plan_id, request, now):
        try:
            with self.db.get_session() as session:
                # Serialize SQLite writes before reading plan/head. Other dialects
                # lock the plan; the unique track revision is a second guard.
                if self.db._engine.dialect.name == 'sqlite':
                    session.execute(text('BEGIN IMMEDIATE'))
                plan = session.scalar(select(PortfolioAllocationPlan).where(
                    PortfolioAllocationPlan.id == plan_id).with_for_update())
                existing = self.decode(session.scalar(select(PortfolioAllocationReview).where(
                    PortfolioAllocationReview.plan_id == plan_id,
                    PortfolioAllocationReview.request_key == request['request_key'])))
                if existing:
                    return self.check_retry(existing, request)
                if plan is None or not plan.is_active:
                    raise LookupError("Active allocation plan not found")
                if plan.version != request['expected_plan_version']:
                    raise AllocationReviewConflict("Plan changed; reload before reviewing")
                target = session.scalar(select(PortfolioAllocationTarget).where(
                    PortfolioAllocationTarget.plan_id == plan_id,
                    PortfolioAllocationTarget.target_key == request['target_key']))
                if target is None:
                    raise LookupError("Allocation target not found")
                head = session.scalar(select(PortfolioAllocationReview).where(
                    PortfolioAllocationReview.plan_id == plan_id,
                    PortfolioAllocationReview.target_key == request['target_key'],
                    PortfolioAllocationReview.horizon == request['horizon'])
                    .order_by(PortfolioAllocationReview.id.desc()).limit(1))
                if (head.id if head else None) != request['expected_previous_id']:
                    raise AllocationReviewConflict("Review changed; reload its latest history")
                payload = dict(request, created_at=now.isoformat(), authority='manual_unverified',
                               target_snapshot=PortfolioAllocationRepository.target_to_dict(target))
                row = PortfolioAllocationReview(plan_id=plan_id, target_key=request['target_key'],
                    horizon=request['horizon'], revision=(head.revision + 1 if head else 1),
                    request_key=request['request_key'], payload_json=json.dumps(payload, ensure_ascii=False))
                session.add(row)
                session.commit()
                session.refresh(row)
                return self.decode(row)
        except IntegrityError as exc:
            existing = self.by_request(plan_id, request['request_key'])
            if existing:
                return self.check_retry(existing, request)
            raise AllocationReviewConflict("Concurrent review changed; reload before retrying") from exc

    def latest(self, plan_id, target_key=None):
        with self.db.get_session() as session:
            heads = select(func.max(PortfolioAllocationReview.id)).where(PortfolioAllocationReview.plan_id == plan_id)
            if target_key is not None:
                heads = heads.where(PortfolioAllocationReview.target_key == target_key)
            heads = heads.group_by(PortfolioAllocationReview.target_key, PortfolioAllocationReview.horizon)
            return [self.decode(row) for row in session.scalars(select(PortfolioAllocationReview)
                    .where(PortfolioAllocationReview.id.in_(heads)).order_by(PortfolioAllocationReview.id.desc()))]

    def history(self, plan_id, target_key, limit, before_id=None):
        with self.db.get_session() as session:
            query = select(PortfolioAllocationReview).where(PortfolioAllocationReview.plan_id == plan_id,
                PortfolioAllocationReview.target_key == target_key)
            if before_id is not None:
                query = query.where(PortfolioAllocationReview.id < before_id)
            return [self.decode(row) for row in session.scalars(query.order_by(
                PortfolioAllocationReview.id.desc()).limit(limit + 1))]
