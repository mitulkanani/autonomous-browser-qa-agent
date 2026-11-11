from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from app.models.schemas import RunReport, RunSummary


class RunStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS qa_runs (
                    run_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    finding_count INTEGER NOT NULL,
                    report_json TEXT NOT NULL
                )"""
            )

    def save(self, report: RunReport) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO qa_runs
                (run_id, title, target_url, status, started_at, duration_ms, finding_count, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(report.run_id), report.title, report.target_url, report.status.value,
                    report.started_at.isoformat(), report.duration_ms, len(report.findings),
                    report.model_dump_json(),
                ),
            )

    def get(self, run_id: UUID) -> RunReport | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM qa_runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return RunReport.model_validate_json(row["report_json"]) if row else None

    def list(self, limit: int = 20) -> list[RunSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT run_id, title, target_url, status, started_at, duration_ms, finding_count
                   FROM qa_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            RunSummary(
                run_id=UUID(row["run_id"]), title=row["title"], target_url=row["target_url"],
                status=row["status"], started_at=row["started_at"],
                duration_ms=row["duration_ms"], finding_count=row["finding_count"],
            )
            for row in rows
        ]
