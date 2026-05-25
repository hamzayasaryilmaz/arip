"""SQLite-backed observation state.

Three tables, all small, all local:

  obs_cursors      (source_name, position, updated_at)
  obs_events       one row per observation processed
  obs_clusters     aggregate by fingerprint

This is local SQLite — same store used by memory module. Observation
mode does not introduce a remote DB. Retention is bounded by the
prune_events_older_than helper below.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence

from .models import AnomalyCluster, CanonicalAnomalyEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs_cursors (
    source_name TEXT NOT NULL PRIMARY KEY,
    position    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obs_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name         TEXT NOT NULL,
    observation_id      TEXT NOT NULL,
    trace_id_hash       TEXT NOT NULL,
    fingerprint         TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    rule_id             TEXT,
    abstention_code     TEXT,
    quality_band        TEXT NOT NULL,
    quality_score       REAL NOT NULL,
    primary_confidence  REAL,
    service_set         TEXT NOT NULL,
    operation_names     TEXT NOT NULL,
    evidence_kinds      TEXT,
    UNIQUE(source_name, observation_id)
);
CREATE INDEX IF NOT EXISTS ix_obs_events_fp        ON obs_events(fingerprint);
CREATE INDEX IF NOT EXISTS ix_obs_events_observed  ON obs_events(observed_at);
CREATE INDEX IF NOT EXISTS ix_obs_events_source    ON obs_events(source_name);

CREATE TABLE IF NOT EXISTS obs_clusters (
    fingerprint            TEXT PRIMARY KEY,
    rule_id                TEXT,
    abstention_code        TEXT,
    first_seen             TEXT NOT NULL,
    last_seen              TEXT NOT NULL,
    recurrence_count       INTEGER NOT NULL,
    dominant_quality_band  TEXT NOT NULL,
    service_set            TEXT NOT NULL,
    operation_names_sample TEXT NOT NULL,
    example_trace_id_hash  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_clusters_last_seen ON obs_clusters(last_seen);
"""


class ObservationStore:
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

    # --- cursors ------------------------------------------------------

    def load_cursor(self, source_name: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT position FROM obs_cursors WHERE source_name = ?",
                (source_name,),
            ).fetchone()
        return row["position"] if row else None

    def save_cursor(self, source_name: str, position: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._conn() as c:
            c.execute(
                """INSERT INTO obs_cursors (source_name, position, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(source_name) DO UPDATE SET
                     position = excluded.position,
                     updated_at = excluded.updated_at""",
                (source_name, position, now),
            )

    # --- events -------------------------------------------------------

    def record_event(self, ev: CanonicalAnomalyEvent) -> bool:
        """Insert one event. Returns True if newly inserted, False if a
        prior observation with the same (source_name, observation_id)
        already exists (idempotent ingestion).
        """
        with self._conn() as c:
            try:
                c.execute(
                    """INSERT INTO obs_events
                       (source_name, observation_id, trace_id_hash, fingerprint,
                        observed_at, rule_id, abstention_code, quality_band,
                        quality_score, primary_confidence, service_set,
                        operation_names, evidence_kinds)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ev.source_name,
                        ev.observation_id,
                        ev.trace_id_hash,
                        ev.fingerprint,
                        ev.observed_at.astimezone(timezone.utc).isoformat(),
                        ev.rule_id,
                        ev.abstention_code,
                        ev.quality_band,
                        ev.quality_score,
                        ev.primary_confidence,
                        ",".join(ev.service_set),
                        ",".join(ev.operation_names),
                        ",".join(ev.evidence_kinds),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    # --- cluster upsert ----------------------------------------------

    def upsert_cluster(self, ev: CanonicalAnomalyEvent) -> None:
        observed_iso = ev.observed_at.astimezone(timezone.utc).isoformat()
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM obs_clusters WHERE fingerprint = ?",
                (ev.fingerprint,),
            ).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO obs_clusters
                       (fingerprint, rule_id, abstention_code, first_seen,
                        last_seen, recurrence_count, dominant_quality_band,
                        service_set, operation_names_sample,
                        example_trace_id_hash)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        ev.fingerprint,
                        ev.rule_id,
                        ev.abstention_code,
                        observed_iso,
                        observed_iso,
                        ev.quality_band,
                        ",".join(ev.service_set),
                        ",".join(ev.operation_names),
                        ev.trace_id_hash,
                    ),
                )
                return
            new_count = row["recurrence_count"] + 1
            new_last = (
                observed_iso if observed_iso > row["last_seen"] else row["last_seen"]
            )
            new_first = (
                observed_iso if observed_iso < row["first_seen"] else row["first_seen"]
            )
            # Dominant quality band: recompute from this cluster's events
            # so it reflects the actual distribution, not just the last one.
            counts = c.execute(
                """SELECT quality_band, COUNT(*) AS n FROM obs_events
                   WHERE fingerprint = ? GROUP BY quality_band""",
                (ev.fingerprint,),
            ).fetchall()
            band_counter = Counter({r["quality_band"]: r["n"] for r in counts})
            band_counter[ev.quality_band] += 0  # already counted; no-op
            dominant_band = band_counter.most_common(1)[0][0] if band_counter else ev.quality_band
            # Operation names sample: take union of existing + new (cap N)
            existing_ops = set(
                (row["operation_names_sample"] or "").split(",")
            ) - {""}
            new_ops = sorted(existing_ops | set(ev.operation_names))[:20]
            existing_services = set((row["service_set"] or "").split(",")) - {""}
            new_services = sorted(existing_services | set(ev.service_set))
            c.execute(
                """UPDATE obs_clusters
                   SET last_seen = ?, first_seen = ?, recurrence_count = ?,
                       dominant_quality_band = ?,
                       service_set = ?, operation_names_sample = ?
                   WHERE fingerprint = ?""",
                (
                    new_last,
                    new_first,
                    new_count,
                    dominant_band,
                    ",".join(new_services),
                    ",".join(new_ops),
                    ev.fingerprint,
                ),
            )

    # --- queries ------------------------------------------------------

    def list_clusters(
        self,
        *,
        kind: str = "any",
        window_days: int | None = None,
        min_recurrence: int = 1,
    ) -> list[AnomalyCluster]:
        """List clusters matching the filter.

        ``kind`` is 'rule' (rule_id IS NOT NULL), 'abstention'
        (abstention_code IS NOT NULL), or 'any'.
        """
        where: list[str] = ["recurrence_count >= ?"]
        params: list[object] = [min_recurrence]
        if kind == "rule":
            where.append("rule_id IS NOT NULL")
        elif kind == "abstention":
            where.append("abstention_code IS NOT NULL")
        if window_days is not None:
            cutoff = (
                datetime.now(tz=timezone.utc) - timedelta(days=window_days)
            ).isoformat()
            where.append("last_seen >= ?")
            params.append(cutoff)
        sql = (
            "SELECT * FROM obs_clusters WHERE "
            + " AND ".join(where)
            + " ORDER BY recurrence_count DESC, last_seen DESC"
        )
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_cluster(r) for r in rows]

    def count_low_quality_events(self, window_days: int | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM obs_events WHERE quality_band = 'low'"
        params: list[object] = []
        if window_days is not None:
            cutoff = (
                datetime.now(tz=timezone.utc) - timedelta(days=window_days)
            ).isoformat()
            sql += " AND observed_at >= ?"
            params.append(cutoff)
        with self._conn() as c:
            row = c.execute(sql, params).fetchone()
        return int(row["n"])

    def quality_band_distribution(
        self, window_days: int | None = None
    ) -> dict[str, int]:
        sql = "SELECT quality_band, COUNT(*) AS n FROM obs_events"
        params: list[object] = []
        if window_days is not None:
            cutoff = (
                datetime.now(tz=timezone.utc) - timedelta(days=window_days)
            ).isoformat()
            sql += " WHERE observed_at >= ?"
            params.append(cutoff)
        sql += " GROUP BY quality_band"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return {r["quality_band"]: int(r["n"]) for r in rows}

    # --- retention ----------------------------------------------------

    def prune_events_older_than(self, retention_days: int) -> int:
        """Drop events older than `retention_days`. Clusters are kept —
        their aggregates persist across pruning. Returns count deleted."""
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM obs_events WHERE observed_at < ?",
                (cutoff,),
            )
            return cur.rowcount


def _row_to_cluster(row: sqlite3.Row) -> AnomalyCluster:
    return AnomalyCluster(
        fingerprint=row["fingerprint"],
        rule_id=row["rule_id"],
        abstention_code=row["abstention_code"],
        first_seen=_parse(row["first_seen"]),
        last_seen=_parse(row["last_seen"]),
        recurrence_count=int(row["recurrence_count"]),
        dominant_quality_band=row["dominant_quality_band"],
        service_set=_split(row["service_set"]),
        operation_names_sample=_split(row["operation_names_sample"]),
        example_trace_id_hash=row["example_trace_id_hash"],
    )


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _split(s: str | None) -> tuple[str, ...]:
    if not s:
        return ()
    return tuple(p for p in s.split(",") if p)
