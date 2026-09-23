"""SQLite-backed run history and lightweight health tracking."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from config import DATA_DIR


class RunTracker:
    """Persist each scheduled or manual pipeline execution."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DATA_DIR / "runs.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    duration_ms INTEGER,
                    error TEXT,
                    metrics_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_logs_run_id ON run_logs(run_id)"
            )

    @contextmanager
    def run(self, mode: str, metadata: Optional[Dict[str, Any]] = None) -> Iterator["RunHandle"]:
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        metrics = dict(metadata or {})
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (run_id, mode, started_at, status, metrics_json)
                VALUES (?, ?, ?, 'RUNNING', ?)
                """,
                (run_id, mode, started_at, json.dumps(metrics, ensure_ascii=False)),
            )

        handle = RunHandle(self, run_id, started_at, metrics)
        try:
            yield handle
        except Exception as exc:
            self._finish(run_id, started_at, "FAILED", metrics, str(exc))
            raise
        else:
            self._finish(run_id, started_at, "SUCCESS", metrics, None)

    def _finish(
        self,
        run_id: str,
        started_at: str,
        status: str,
        metrics: Dict[str, Any],
        error: Optional[str],
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - datetime.fromisoformat(started_at)).total_seconds() * 1000)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE runs
                SET finished_at = ?, status = ?, duration_ms = ?, error = ?, metrics_json = ?
                WHERE run_id = ?
                """,
                (
                    finished_at.isoformat(),
                    status,
                    duration_ms,
                    error,
                    json.dumps(metrics, ensure_ascii=False, default=str),
                    run_id,
                ),
            )

    def log(self, run_id: str, level: str, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO run_logs (run_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, level, message, datetime.now(timezone.utc).isoformat()),
            )

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def latest(self) -> Optional[Dict[str, Any]]:
        rows = self.list_recent(limit=1)
        return rows[0] if rows else None


class RunHandle:
    def __init__(self, tracker: RunTracker, run_id: str, started_at: str, metrics: Dict[str, Any]):
        self.tracker = tracker
        self.run_id = run_id
        self.started_at = started_at
        self.metrics = metrics

    @property
    def id(self) -> str:
        return self.run_id

    def set_metrics(self, **values: Any) -> None:
        self.metrics.update(values)

    def log(self, level: str, message: str) -> None:
        self.tracker.log(self.run_id, level, message)
