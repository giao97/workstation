"""Immutable ETF evidence storage. Never updates holdings, trades, budgets or cash."""
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.core.market_events import encode
from src.storage import DatabaseManager, EtfCompositionSnapshot


class EtfCompositionRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    @staticmethod
    def payload(row):
        return dict(json.loads(row.payload_json), id=row.id, content_hash=row.content_hash,
                    recorded_at=row.recorded_at.isoformat() + 'Z') if row else None

    def save(self, document, fingerprint, now):
        from datetime import date
        try:
            with self.db.get_session() as session:
                existing = session.scalar(select(EtfCompositionSnapshot).where(EtfCompositionSnapshot.content_hash == fingerprint))
                if existing:
                    return self.payload(existing)
                row = EtfCompositionSnapshot(content_hash=fingerprint, fund_symbol=document['fund_symbol'],
                    fund_market=document['fund_market'], holdings_as_of=date.fromisoformat(document['holdings_as_of']),
                    recorded_at=now.replace(tzinfo=None), payload_json=encode(document))
                session.add(row)
                session.commit()
                session.refresh(row)
                return self.payload(row)
        except IntegrityError:
            with self.db.get_session() as session:
                row = session.scalar(select(EtfCompositionSnapshot).where(EtfCompositionSnapshot.content_hash == fingerprint))
                if row is None:
                    raise
                return self.payload(row)

    def latest(self):
        # Windowing bounds output per identity without truncating older identities.
        from sqlalchemy import func
        ranked = select(EtfCompositionSnapshot.id,
            func.row_number().over(partition_by=(EtfCompositionSnapshot.fund_market, EtfCompositionSnapshot.fund_symbol),
                order_by=(EtfCompositionSnapshot.holdings_as_of.desc(), EtfCompositionSnapshot.id.desc())).label('rank')).subquery()
        with self.db.get_session() as session:
            rows = session.scalars(select(EtfCompositionSnapshot).join(ranked, ranked.c.id == EtfCompositionSnapshot.id)
                .where(ranked.c.rank == 1).order_by(EtfCompositionSnapshot.fund_symbol))
            return [self.payload(r) for r in rows]

    def get(self, snapshot_id):
        with self.db.get_session() as session:
            return self.payload(session.get(EtfCompositionSnapshot, snapshot_id))
