"""Local-only composition review, import and current recorded-holding overlap."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.config import get_config
from src.core.etf_exposure import composition_coverage, compare_compositions
from src.core.market_events import digest
from src.repositories.etf_composition_repo import EtfCompositionRepository
from src.services.market_event_holdings import load_recorded_holding_scope


class EtfExposureService:
    def __init__(self, repo=None, clock=None, config=None):
        self.repo = repo or EtfCompositionRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.config = config or get_config()

    def preview(self, snapshot):
        now = self.clock().astimezone(timezone.utc)
        today = now.astimezone(ZoneInfo('America/New_York')).date()
        published = snapshot.source_published_at
        if snapshot.holdings_as_of > today or (published is not None and published > now):
            raise ValueError('Future composition/publication is not eligible')
        if published is not None and snapshot.holdings_as_of > published.astimezone(ZoneInfo('America/New_York')).date():
            raise ValueError('Publication cannot precede the composition date')
        payload = snapshot.model_dump(mode='json')
        payload['constituents'].sort(key=lambda c: (c['market'], c['symbol']))
        from decimal import Decimal
        for row in payload['constituents']:
            row['weight_pct'] = format(Decimal(row['weight_pct']).normalize(), 'f')
        payload['source_published_at'] = published.astimezone(timezone.utc).isoformat() if published else None
        payload['verification'] = 'manual_attestation_not_independent_verification'
        return {'snapshot': payload, 'content_hash': digest(payload),
                'coverage': composition_coverage(payload, today), 'can_write_portfolio': False}

    def save(self, request):
        checked = self.preview(request.snapshot)
        return self.repo.save(checked['snapshot'], checked['content_hash'], self.clock().astimezone(timezone.utc))

    def report(self, account_id=None):
        now = self.clock().astimezone(timezone.utc)
        holdings, context = load_recorded_holding_scope(self.repo.db, now,
            self.config.market_event_profile_path, account_id)
        if len(holdings) > 100:
            raise ValueError('Select an account with at most 100 distinct holdings for this review')
        snapshots = self.repo.latest()
        today = now.astimezone(ZoneInfo('America/New_York')).date()
        result = compare_compositions(snapshots, holdings, today)
        # Bound displayed details, never the calculation universe or reported counts.
        for pair in result['pairs']:
            pair['shared'] = pair['shared'][:20]
        for fund in result['funds']:
            fund['row_count'] = len(fund.pop('constituents'))
        return dict(result, generated_at=now.isoformat(), holdings=holdings, holding_context=context,
                    account_id=account_id, freshness_policy_days=7,
                    library_count=len(snapshots), source_mode='manual_reviewed_snapshot')
