"""Append-only market-news research storage. No portfolio writes."""
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.market_events import encode
from src.storage import DatabaseManager, MarketEventBrief, MarketEventVerification, MarketNewsEvidence


class MarketEventRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def retain_evidence(self, payload, now):
        evidence_id = payload['evidence_id']
        frozen = dict(payload, first_seen_at=now.isoformat())
        try:
            with self.db.get_session() as session:
                row = session.get(MarketNewsEvidence, evidence_id)
                if row:
                    return json.loads(row.payload_json)
                session.add(MarketNewsEvidence(evidence_id=evidence_id,
                            first_seen_at=now.replace(tzinfo=None), payload_json=encode(frozen)))
                session.commit()
                return frozen
        except IntegrityError:
            with self.db.get_session() as session:
                row = session.get(MarketNewsEvidence, evidence_id)
                if row is None:
                    raise
                return json.loads(row.payload_json)

    @staticmethod
    def _brief(row):
        return dict(json.loads(row.payload_json), id=row.id) if row else None

    def by_key(self, request_key):
        with self.db.get_session() as session:
            return self._brief(session.scalar(select(MarketEventBrief).where(MarketEventBrief.request_key == request_key)))

    def get(self, brief_id):
        with self.db.get_session() as session:
            return self._brief(session.get(MarketEventBrief, brief_id))

    def baseline(self, market, start, before):
        """First original snapshot of the local day, never an interpretation retry."""
        with self.db.get_session() as session:
            query = select(MarketEventBrief).where(
                MarketEventBrief.market == market,
                MarketEventBrief.captured_at >= start.replace(tzinfo=None),
                MarketEventBrief.captured_at < before.replace(tzinfo=None),
            ).order_by(MarketEventBrief.captured_at, MarketEventBrief.id)
            for row in session.scalars(query):
                brief = self._brief(row)
                if not brief.get('parent_brief_id'):
                    return brief
        return None

    def list(self, market=None, limit=30):
        with self.db.get_session() as session:
            query = select(MarketEventBrief).order_by(MarketEventBrief.id.desc()).limit(limit)
            if market:
                query = query.where(MarketEventBrief.market == market)
            return [dict(id=r.id, **{k: v for k, v in json.loads(r.payload_json).items()
                    if k in {'market', 'captured_at', 'coverage', 'language', 'parent_brief_id', 'analysis_retried_at'}}) for r in session.scalars(query)]

    def save(self, key, payload, now):
        try:
            with self.db.get_session() as session:
                row = MarketEventBrief(request_key=key, market=payload['market'],
                                       captured_at=now.replace(tzinfo=None), payload_json=encode(payload))
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._brief(row)
        except IntegrityError:
            existing = self.by_key(key)
            if existing is None:
                raise
            if existing.get('request_hash') != payload.get('request_hash'):
                raise ValueError('Request key already belongs to different parameters')
            return existing

    def reviews(self, event_keys, as_of=None):
        if not event_keys:
            return []
        with self.db.get_session() as session:
            query = select(MarketEventVerification).where(MarketEventVerification.event_key.in_(event_keys))
            if as_of:
                query = query.where(MarketEventVerification.checked_at <= as_of.replace(tzinfo=None))
            return [dict(json.loads(row.payload_json), id=row.id, brief_id=row.brief_id,
                         event_key=row.event_key, checked_at=row.checked_at.isoformat() + 'Z')
                    for row in session.scalars(query.order_by(MarketEventVerification.id))]

    def verify(self, brief_id, request, now):
        with self.db.get_session() as session:
            row = MarketEventVerification(brief_id=brief_id, event_key=request['event_key'],
                        checked_at=now.replace(tzinfo=None), payload_json=encode(dict(request, authority='user_attestation')))
            session.add(row)
            session.commit()
            session.refresh(row)
            return dict(json.loads(row.payload_json), id=row.id, brief_id=row.brief_id,
                        event_key=row.event_key, checked_at=row.checked_at.isoformat() + 'Z')
