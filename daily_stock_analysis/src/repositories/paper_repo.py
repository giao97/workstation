"""Append-only paper research storage; no portfolio account/trade access."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.storage import DatabaseManager, PaperExperimentRecord, PaperOutcomeRecord


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def experiment_dict(row):
    return dict(id=row.id, signal_id=row.signal_id, captured_at=row.captured_at.isoformat() + "Z",
                snapshot=json.loads(row.snapshot_json), assumptions=json.loads(row.assumptions_json),
                snapshot_hash=row.snapshot_hash)


class PaperRepository:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def by_key(self, key):
        with self.db.get_session() as session:
            row = session.scalar(select(PaperExperimentRecord).where(PaperExperimentRecord.request_key == key))
            return experiment_dict(row) if row else None

    def get(self, experiment_id):
        with self.db.get_session() as session:
            row = session.get(PaperExperimentRecord, experiment_id)
            return experiment_dict(row) if row else None

    def list(self, signal_id, limit=50):
        with self.db.get_session() as session:
            query = select(PaperExperimentRecord).order_by(PaperExperimentRecord.id.desc()).limit(limit)
            if signal_id is not None:
                query = query.where(PaperExperimentRecord.signal_id == signal_id)
            return [experiment_dict(row) for row in session.scalars(query)]

    def create(self, key, signal_id, snapshot, assumptions, captured_at):
        checksum = digest(dict(snapshot=snapshot, assumptions=assumptions, captured_at=captured_at.isoformat() + "Z"))
        try:
            with self.db.get_session() as session:
                row = PaperExperimentRecord(request_key=key, signal_id=signal_id, captured_at=captured_at,
                                            snapshot_json=encode(snapshot), assumptions_json=encode(assumptions),
                                            snapshot_hash=checksum)
                session.add(row)
                session.commit()
                session.refresh(row)
                return experiment_dict(row)
        except IntegrityError:
            existing = self.by_key(key)
            if not existing:
                raise
            return existing

    def outcomes(self, experiment_id, engine):
        with self.db.get_session() as session:
            rows = session.scalars(select(PaperOutcomeRecord).where(
                PaperOutcomeRecord.experiment_id == experiment_id, PaperOutcomeRecord.engine_version == engine))
            return {row.horizon: json.loads(row.result_json) for row in rows}

    def save_outcome(self, experiment_id, horizon, engine, result, evidence, now):
        try:
            with self.db.get_session() as session:
                session.add(PaperOutcomeRecord(experiment_id=experiment_id, horizon=horizon,
                                              engine_version=engine, result_json=encode(result),
                                              evidence_json=encode(evidence), observed_at=now))
                session.commit()
        except IntegrityError:
            if horizon not in self.outcomes(experiment_id, engine):
                raise
        return self.outcomes(experiment_id, engine)[horizon]

    def evidence(self, experiment_id, horizon, engine):
        with self.db.get_session() as session:
            row = session.scalar(select(PaperOutcomeRecord).where(
                PaperOutcomeRecord.experiment_id == experiment_id, PaperOutcomeRecord.horizon == horizon,
                PaperOutcomeRecord.engine_version == engine))
            return json.loads(row.evidence_json) if row else None
