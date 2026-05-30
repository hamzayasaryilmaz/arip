"""Tests for observation mode (Phase A).

Discipline:
  - ingestion is read-only, cursor-based, and idempotent
  - the engine path is the same one investigate uses (no parallel reasoning)
  - cluster recurrence is exactly the count of distinct observations of a
    given fingerprint
  - quality_band propagates from the existing quality assessor
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from arip_core.observation.digest import build_digest, render_digest
from arip_core.observation.pipeline import observe
from arip_core.observation.sources import (
    DirectoryTraceSource,
    JsonlTraceSource,
)
from arip_core.observation.store import ObservationStore

NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


# ---------- fixture helpers ----------------------------------------


def _retry_attempt_span(
    *,
    trace_id: str,
    span_id: str,
    n: int,
    backoff_ms: int,
    start_ms: int,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": None,
        "service_name": "inventory-service",
        "operation_name": "inventory.reserve_attempt",
        "start_time": (NOW + timedelta(milliseconds=start_ms)).isoformat(),
        "duration_us": 3_000,
        "status": "ERROR",
        "status_message": "upstream 503: service temporarily unavailable",
        "attributes": {
            "retry.attempt": n,
            "retry.max_attempts": 5,
            "retry.backoff_ms": backoff_ms,
            "retry.policy": "exponential",
            "retry.reason": "upstream 503: service temporarily unavailable",
            "retry.retriable": True,
        },
        "events": [],
    }


def _retry_storm_bundle(trace_id: str, *, captured_at: datetime) -> dict[str, Any]:
    spans = [
        _retry_attempt_span(
            trace_id=trace_id, span_id=f"a{i}", n=i, backoff_ms=50 * (2 ** (i - 1)), start_ms=10 * i
        )
        for i in range(1, 6)
    ]
    logs = [
        {
            "timestamp": (captured_at + timedelta(milliseconds=15)).isoformat(),
            "service_name": "inventory-service",
            "level": "ERROR",
            "message": "inventory.reserve_attempt: upstream returned 503",
            "trace_id": trace_id,
            "fields": {"attempt": 3},
        }
    ]
    return {
        "trace_id": trace_id,
        "captured_at": captured_at.isoformat(),
        "spans": spans,
        "logs": logs,
    }


def _empty_trace_bundle(trace_id: str, *, captured_at: datetime) -> dict[str, Any]:
    """A trace with a single OK span — no anomaly. Engine abstains."""
    return {
        "trace_id": trace_id,
        "captured_at": captured_at.isoformat(),
        "spans": [
            {
                "trace_id": trace_id,
                "span_id": "ok1",
                "parent_span_id": None,
                "service_name": "payment-service",
                "operation_name": "POST /checkout",
                "start_time": captured_at.isoformat(),
                "duration_us": 5_000,
                "status": "OK",
                "status_message": "",
                "attributes": {"http.status_code": 200},
                "events": [],
            }
        ],
        "logs": [],
    }


def _write_jsonl(path: Path, bundles: list[dict[str, Any]]) -> None:
    with path.open("w") as fh:
        for b in bundles:
            fh.write(json.dumps(b))
            fh.write("\n")


# ---------- ingestion idempotency ----------------------------------


def test_idempotent_ingestion_same_file_run_twice(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [
        _retry_storm_bundle(f"trace-{i}", captured_at=NOW + timedelta(minutes=i)) for i in range(3)
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    source = JsonlTraceSource(jsonl)

    s1 = observe(source=source, store=store, budget=10)
    assert s1.events_new == 3
    assert s1.events_skipped_idempotent == 0

    # Re-running with the same cursor would normally skip ingested lines.
    # To prove idempotency, we forcibly reset the cursor and re-ingest:
    store.save_cursor(source.name, "0")
    s2 = observe(source=source, store=store, budget=10)
    assert s2.events_new == 0
    assert s2.events_skipped_idempotent == 3


def test_cursor_resumes_partial_run(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [
        _retry_storm_bundle(f"trace-{i}", captured_at=NOW + timedelta(minutes=i)) for i in range(5)
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    source = JsonlTraceSource(jsonl)

    # First run: budget of 2 — only first two are ingested.
    s1 = observe(source=source, store=store, budget=2)
    assert s1.traces_observed == 2
    assert s1.events_new == 2

    # Second run: continues from cursor — picks up the remaining 3.
    s2 = observe(source=source, store=store, budget=10)
    assert s2.traces_observed == 3
    assert s2.events_new == 3


# ---------- gzip support -------------------------------------------


def test_jsonl_gz_source(tmp_path: Path) -> None:
    raw = tmp_path / "telemetry.jsonl"
    bundles = [_retry_storm_bundle("trace-gz", captured_at=NOW)]
    _write_jsonl(raw, bundles)

    gz = tmp_path / "telemetry.jsonl.gz"
    with gz.open("wb") as out, gzip.open(out, "wb") as gout:  # type: ignore[arg-type]
        gout.write(raw.read_bytes())

    store = ObservationStore(tmp_path / "observation.db")
    s = observe(source=JsonlTraceSource(gz), store=store, budget=10)
    assert s.events_new == 1


# ---------- directory source ---------------------------------------


def test_directory_source(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundles"
    bundle_dir.mkdir()
    for i in range(3):
        b = _retry_storm_bundle(f"trace-d-{i}", captured_at=NOW + timedelta(minutes=i))
        (bundle_dir / f"0{i}.json").write_text(json.dumps(b))

    store = ObservationStore(tmp_path / "observation.db")
    source = DirectoryTraceSource(bundle_dir)
    s = observe(source=source, store=store, budget=10)
    assert s.events_new == 3

    # Adding a new file is picked up by the next run.
    new_b = _retry_storm_bundle("trace-d-3", captured_at=NOW + timedelta(minutes=3))
    (bundle_dir / "03.json").write_text(json.dumps(new_b))
    s2 = observe(source=source, store=store, budget=10)
    assert s2.events_new == 1


# ---------- clustering & recurrence --------------------------------


def test_retry_storm_cluster_recurrence(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    # 4 identical-shape retry_storm traces.
    bundles = [
        _retry_storm_bundle(f"trace-{i}", captured_at=NOW + timedelta(minutes=i)) for i in range(4)
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=10)

    rule_clusters = store.list_clusters(kind="rule")
    assert len(rule_clusters) == 1, "all four traces should share one fingerprint"
    c = rule_clusters[0]
    assert c.rule_id == "retry_storm"
    assert c.recurrence_count == 4
    assert "inventory-service" in c.service_set


def test_abstention_cluster_recorded(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [
        _empty_trace_bundle(f"ok-{i}", captured_at=NOW + timedelta(minutes=i)) for i in range(2)
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=10)

    abstention_clusters = store.list_clusters(kind="abstention")
    assert len(abstention_clusters) >= 1
    # No rule-grounded cluster for OK traces.
    assert store.list_clusters(kind="rule") == []
    # And the abstention code is one of the known codes.
    codes = {c.abstention_code for c in abstention_clusters}
    assert codes <= {
        "no_primary_trace",
        "empty_telemetry",
        "no_rule_matched",
        "weak_evidence",
        "conflicting_hypotheses",
    }


# ---------- quality propagation ------------------------------------


def test_quality_band_propagates(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    _write_jsonl(jsonl, [_retry_storm_bundle("trace-q", captured_at=NOW)])

    store = ObservationStore(tmp_path / "observation.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=10)

    dist = store.quality_band_distribution()
    assert sum(dist.values()) == 1
    assert next(iter(dist)) in {"high", "medium", "low"}


# ---------- digest rendering ---------------------------------------


def test_digest_contains_rule_cluster_and_disclaimer(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [
        _retry_storm_bundle(f"trace-{i}", captured_at=NOW + timedelta(minutes=i)) for i in range(3)
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    summary = observe(source=JsonlTraceSource(jsonl), store=store, budget=10)

    digest = build_digest(store, window_label="test", summary=summary)
    md = render_digest(digest)

    assert "Recurring patterns (rule-grounded)" in md
    assert "retry_storm" in md
    # The honesty section is non-negotiable.
    assert "What this digest is NOT" in md
    assert "Not a list of confirmed root causes" in md
    # The run-summary section is present when summary is passed.
    assert "Run summary" in md


def test_digest_handles_empty_store(tmp_path: Path) -> None:
    store = ObservationStore(tmp_path / "observation.db")
    digest = build_digest(store, window_label="empty")
    md = render_digest(digest)
    assert "No rule-grounded recurring patterns" in md
    assert "What this digest is NOT" in md


# ---------- read-only contract -------------------------------------


def test_source_never_mutates_input_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [_retry_storm_bundle("trace-immut", captured_at=NOW)]
    _write_jsonl(jsonl, bundles)
    before = jsonl.read_bytes()
    mtime_before = jsonl.stat().st_mtime

    store = ObservationStore(tmp_path / "observation.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=10)

    assert jsonl.read_bytes() == before, "source file must not be mutated"
    assert jsonl.stat().st_mtime == pytest.approx(mtime_before, abs=0.01)


# ---------- end-to-end shape check ----------------------------------


def test_mixed_anomaly_and_ok_traces(tmp_path: Path) -> None:
    jsonl = tmp_path / "telemetry.jsonl"
    bundles = [
        _retry_storm_bundle("trace-storm-1", captured_at=NOW),
        _empty_trace_bundle("trace-ok-1", captured_at=NOW + timedelta(minutes=1)),
        _retry_storm_bundle("trace-storm-2", captured_at=NOW + timedelta(minutes=2)),
        _empty_trace_bundle("trace-ok-2", captured_at=NOW + timedelta(minutes=3)),
    ]
    _write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "observation.db")
    summary = observe(source=JsonlTraceSource(jsonl), store=store, budget=10)
    assert summary.events_new == 4

    rule_clusters = store.list_clusters(kind="rule")
    abstention_clusters = store.list_clusters(kind="abstention")
    rule_recurrence_total = sum(c.recurrence_count for c in rule_clusters)
    abstention_recurrence_total = sum(c.recurrence_count for c in abstention_clusters)
    assert rule_recurrence_total + abstention_recurrence_total == 4


# ---------- cursor format ------------------------------------------


def test_cursor_is_persisted_per_source(tmp_path: Path) -> None:
    jsonl_a = tmp_path / "a.jsonl"
    jsonl_b = tmp_path / "b.jsonl"
    _write_jsonl(jsonl_a, [_retry_storm_bundle("a1", captured_at=NOW)])
    _write_jsonl(jsonl_b, [_retry_storm_bundle("b1", captured_at=NOW)])

    store = ObservationStore(tmp_path / "observation.db")
    src_a = JsonlTraceSource(jsonl_a)
    src_b = JsonlTraceSource(jsonl_b)
    observe(source=src_a, store=store, budget=10)
    observe(source=src_b, store=store, budget=10)

    assert store.load_cursor(src_a.name) is not None
    assert store.load_cursor(src_b.name) is not None
    assert store.load_cursor(src_a.name) != "0"
