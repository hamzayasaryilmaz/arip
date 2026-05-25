"""SQLite-backed memory store.

Two tables, both intentionally small:

  investigations   one row per failure ARIP investigated
  test_runs        one row per test execution (pass or fail)

Stored as SQLite because:
  * zero deps, ships with Python
  * works in CI runners + dev laptops
  * cheap to ship/share (single file)
  * sufficient for the volumes a single CI org produces
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ..reporter.models import HistoryContext, InvestigationReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name           TEXT NOT NULL,
    trace_id            TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    environment         TEXT,
    fingerprint         TEXT,
    primary_rule_id     TEXT,
    primary_title       TEXT,
    primary_confidence  REAL,
    primary_severity    TEXT,
    abstention_code     TEXT,
    report_path         TEXT
);
CREATE INDEX IF NOT EXISTS ix_inv_fingerprint ON investigations(fingerprint);
CREATE INDEX IF NOT EXISTS ix_inv_test_name   ON investigations(test_name);
CREATE INDEX IF NOT EXISTS ix_inv_timestamp   ON investigations(timestamp);

CREATE TABLE IF NOT EXISTS test_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name    TEXT NOT NULL,
    status       TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    environment  TEXT,
    trace_id     TEXT
);
CREATE INDEX IF NOT EXISTS ix_tr_test_name ON test_runs(test_name);
CREATE INDEX IF NOT EXISTS ix_tr_timestamp ON test_runs(timestamp);
"""


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # --- writes -------------------------------------------------------

    def record_investigation(
        self,
        report: InvestigationReport,
        fingerprint: str | None,
        report_path: str | None,
    ) -> None:
        prim = report.primary_hypothesis
        with self._conn() as c:
            c.execute(
                """INSERT INTO investigations
                   (test_name, trace_id, timestamp, environment, fingerprint,
                    primary_rule_id, primary_title, primary_confidence, primary_severity,
                    abstention_code, report_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.failure.test_name,
                    report.failure.trace_id,
                    report.failure.timestamp.astimezone(timezone.utc).isoformat(),
                    report.failure.environment,
                    fingerprint,
                    prim.rule_id if prim else None,
                    prim.title if prim else None,
                    prim.confidence if prim else None,
                    prim.severity if prim else None,
                    report.abstention.code if report.abstention else None,
                    report_path,
                ),
            )

    def record_test_run(
        self,
        test_name: str,
        status: str,
        timestamp: datetime,
        environment: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO test_runs (test_name, status, timestamp, environment, trace_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    test_name,
                    status,
                    timestamp.astimezone(timezone.utc).isoformat(),
                    environment,
                    trace_id,
                ),
            )

    def record_test_runs_bulk(self, rows: list[tuple[str, str, datetime, str | None, str | None]]) -> None:
        with self._conn() as c:
            c.executemany(
                """INSERT INTO test_runs (test_name, status, timestamp, environment, trace_id)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (n, s, t.astimezone(timezone.utc).isoformat(), env, tid)
                    for (n, s, t, env, tid) in rows
                ],
            )

    # --- reads --------------------------------------------------------

    def history_for_fingerprint(
        self,
        fingerprint: str,
        window_days: int = 14,
    ) -> HistoryContext:
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=window_days)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT timestamp, test_name FROM investigations WHERE fingerprint = ? ORDER BY timestamp",
                (fingerprint,),
            ).fetchall()
        if not rows:
            return HistoryContext(
                fingerprint=fingerprint,
                occurrences_total=0,
                occurrences_window=0,
                window_days=window_days,
                first_seen=None,
                last_seen=None,
                affected_tests=[],
            )
        timestamps = [r["timestamp"] for r in rows]
        within_window = [t for t in timestamps if t >= cutoff]
        return HistoryContext(
            fingerprint=fingerprint,
            occurrences_total=len(rows),
            occurrences_window=len(within_window),
            window_days=window_days,
            first_seen=_parse(timestamps[0]),
            last_seen=_parse(timestamps[-1]),
            affected_tests=sorted({r["test_name"] for r in rows}),
        )

    def test_run_stats(
        self,
        test_name: str,
        last_n: int = 20,
    ) -> tuple[int, int]:
        """Return ``(considered, fails)`` over the last N runs of a test."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT status FROM test_runs WHERE test_name = ? ORDER BY timestamp DESC LIMIT ?",
                (test_name, last_n),
            ).fetchall()
        considered = len(rows)
        fails = sum(1 for r in rows if r["status"] == "failed")
        return considered, fails


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
