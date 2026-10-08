"""Independent long-term/tactical review tracks; never allocate or move money."""
from datetime import datetime, timezone

from src.repositories.allocation_review_repo import AllocationReviewRepository
from src.repositories.portfolio_allocation_repo import PortfolioAllocationRepository
from src.schemas.allocation_review import AllocationReviewWrite


class AllocationReviewService:
    def __init__(self, repo=None, clock=None):
        self.repo = repo or AllocationReviewRepository()
        self.plans = PortfolioAllocationRepository(self.repo.db)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _plan(self, plan_id):
        found = self.plans.get_plan(plan_id, include_inactive=True)
        if found is None:
            raise LookupError("Allocation plan not found")
        return found[0]

    @staticmethod
    def state(item, plan, now):
        due = datetime.fromisoformat(item['review_due_at'].replace('Z', '+00:00'))
        state = ('plan_inactive' if not plan.is_active else
                 'plan_changed' if plan.version != item['expected_plan_version'] else
                 'due' if now >= due else 'active')
        return dict(item, state=state)

    def append(self, plan_id, request):
        validated = AllocationReviewWrite.model_validate(request)
        payload = validated.model_dump(mode='json')
        now = self.clock()
        existing = self.repo.by_request(plan_id, validated.request_key)
        if existing:
            item = self.repo.check_retry(existing, payload)
        else:
            if validated.review_due_at <= now:
                raise ValueError("Next review must be in the future; overdue reviews are never auto-renewed")
            item = self.repo.append(plan_id, payload, now)
        return self.state(item, self._plan(plan_id), now)

    def latest(self, plan_id):
        plan, now = self._plan(plan_id), self.clock()
        return [self.state(item, plan, now) for item in self.repo.latest(plan_id)]

    def list(self, plan_id, target_key, limit=20, before_id=None):
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        plan, now = self._plan(plan_id), self.clock()
        items = self.repo.history(plan_id, target_key, limit, before_id)
        return dict(plan_version=plan.version,
                    latest=[self.state(item, plan, now) for item in self.repo.latest(plan_id, target_key)],
                    items=[self.state(item, plan, now) for item in items[:limit]],
                    next_before_id=items[limit - 1]['id'] if len(items) > limit else None)
