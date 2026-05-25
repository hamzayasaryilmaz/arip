"""Synthetic telemetry generators for Phase A stress testing.

These build messy, production-shaped trace bundles for `arip observe`
to chew on. They are NOT used by the rule-level unit tests — those use
hand-crafted minimal fixtures. These exist specifically to validate
observation behaviour under noise.

Design intent: every generator returns a list of trace-bundle dicts in
the JSONL-source shape (see arip_core/observation/sources/jsonl.py).
Generators are deterministic when seeded so stress tests stay
reproducible.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE = datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc)


# ---------- low-level builders --------------------------------------


def _span(
    *,
    trace_id: str,
    span_id: str,
    operation_name: str,
    service_name: str = "payment-service",
    parent_span_id: str | None = None,
    start_offset_ms: int = 0,
    duration_us: int = 5_000,
    status: str = "OK",
    status_message: str = "",
    attributes: dict[str, Any] | None = None,
    base: datetime = BASE,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "service_name": service_name,
        "operation_name": operation_name,
        "start_time": (base + timedelta(milliseconds=start_offset_ms)).isoformat(),
        "duration_us": duration_us,
        "status": status,
        "status_message": status_message,
        "attributes": attributes or {},
        "events": [],
    }


def _log(
    *,
    trace_id: str | None,
    service_name: str,
    level: str,
    message: str,
    timestamp_offset_ms: int = 0,
    base: datetime = BASE,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": (base + timedelta(milliseconds=timestamp_offset_ms)).isoformat(),
        "service_name": service_name,
        "level": level,
        "message": message,
        "trace_id": trace_id,
        "fields": fields or {},
    }


# ---------- trace-shape generators ----------------------------------


def retry_storm_trace(trace_id: str, *, attempts: int = 5, base: datetime = BASE) -> dict[str, Any]:
    spans = [
        _span(
            trace_id=trace_id,
            span_id=f"a{i}",
            operation_name="inventory.reserve_attempt",
            service_name="inventory-service",
            start_offset_ms=i * 60,
            duration_us=3_000,
            status="ERROR",
            status_message="upstream 503: service temporarily unavailable",
            attributes={
                "retry.attempt": i,
                "retry.max_attempts": 5,
                "retry.backoff_ms": 50 * (2 ** (i - 1)),
                "retry.policy": "exponential",
                "retry.reason": "upstream 503: service temporarily unavailable",
                "retry.retriable": True,
            },
            base=base,
        )
        for i in range(1, attempts + 1)
    ]
    logs = [
        _log(
            trace_id=trace_id,
            service_name="inventory-service",
            level="ERROR",
            message="inventory.reserve_attempt: upstream returned 503",
            timestamp_offset_ms=30,
            base=base,
        )
    ]
    return _bundle(trace_id, spans, logs, base=base)


def pool_exhaustion_trace(trace_id: str, *, base: datetime = BASE) -> dict[str, Any]:
    spans = [
        _span(
            trace_id=trace_id,
            span_id="acq",
            operation_name="db.acquire_connection",
            service_name="inventory-service",
            duration_us=1_500_000,
            status="ERROR",
            status_message="pool empty",
            attributes={
                "db.system": "postgresql",
                "db.pool.acquired": 10,
                "db.pool.max": 10,
                "db.pool.wait_ms": 1500,
                "db.pool.empty_acquires_total": 47,
            },
            base=base,
        ),
        _span(
            trace_id=trace_id,
            span_id="handle",
            operation_name="handle_reserve",
            service_name="inventory-service",
            parent_span_id="acq",
            start_offset_ms=1500,
            duration_us=2_000,
            status="ERROR",
            status_message="could not acquire connection",
            base=base,
        ),
    ]
    logs = [
        _log(
            trace_id=trace_id,
            service_name="inventory-service",
            level="ERROR",
            message="db pool exhausted: 10/10 in use, waited 1500ms",
            timestamp_offset_ms=1500,
            base=base,
        )
    ]
    return _bundle(trace_id, spans, logs, base=base)


def downstream_error_trace(trace_id: str, *, base: datetime = BASE) -> dict[str, Any]:
    spans = [
        _span(
            trace_id=trace_id,
            span_id="p",
            operation_name="POST /checkout",
            service_name="payment-service",
            status="ERROR",
            status_message="downstream failure",
            attributes={"http.status_code": 503},
            base=base,
        ),
        _span(
            trace_id=trace_id,
            span_id="i",
            operation_name="inventory.reserve",
            service_name="inventory-service",
            parent_span_id="p",
            start_offset_ms=10,
            duration_us=5_000,
            status="ERROR",
            status_message="reserve failed",
            attributes={"http.status_code": 503},
            base=base,
        ),
    ]
    logs = [
        _log(
            trace_id=trace_id,
            service_name="inventory-service",
            level="ERROR",
            message="inventory.reserve: out of stock or upstream error",
            timestamp_offset_ms=10,
            base=base,
        )
    ]
    return _bundle(trace_id, spans, logs, base=base)


def healthy_trace(trace_id: str, *, base: datetime = BASE) -> dict[str, Any]:
    spans = [
        _span(
            trace_id=trace_id,
            span_id="ok",
            operation_name="POST /checkout",
            service_name="payment-service",
            duration_us=5_000,
            status="OK",
            attributes={"http.status_code": 200},
            base=base,
        )
    ]
    return _bundle(trace_id, spans, [], base=base)


def orphan_span_trace(trace_id: str, *, base: datetime = BASE) -> dict[str, Any]:
    """Non-root span whose parent_span_id is not in the bundle.
    Propagation_health coverage will be < 1.0 → quality band hit."""
    spans = [
        _span(
            trace_id=trace_id,
            span_id="orphan",
            operation_name="inventory.reserve",
            service_name="inventory-service",
            parent_span_id="missing-parent",
            status="ERROR",
            status_message="reserve failed",
            attributes={"http.status_code": 500},
            base=base,
        )
    ]
    return _bundle(trace_id, spans, [], base=base)


def burst_outage_traces(
    n: int = 200, *, start: datetime = BASE, seed: int = 0
) -> list[dict[str, Any]]:
    """Same root cause (retry_storm against inventory-service) repeated N
    times across a short window. Stress test: cluster stability."""
    rng = random.Random(seed)
    bundles: list[dict[str, Any]] = []
    for i in range(n):
        tid = f"burst-{i:05d}"
        # Slight per-trace variation in attempt count so the engine sees
        # natural noise. Fingerprint should still collapse.
        attempts = rng.choice([3, 4, 5, 5, 5])
        base = start + timedelta(milliseconds=i * 100)
        bundles.append(retry_storm_trace(tid, attempts=attempts, base=base))
    return bundles


def cascading_failure_traces(
    n: int = 50, *, start: datetime = BASE, seed: int = 1
) -> list[dict[str, Any]]:
    """A burst that mixes downstream_error + retry_storm + pool_exhaustion
    in proportions a real outage might produce."""
    rng = random.Random(seed)
    bundles: list[dict[str, Any]] = []
    for i in range(n):
        tid = f"casc-{i:05d}"
        base = start + timedelta(milliseconds=i * 250)
        roll = rng.random()
        if roll < 0.5:
            bundles.append(retry_storm_trace(tid, attempts=5, base=base))
        elif roll < 0.85:
            bundles.append(downstream_error_trace(tid, base=base))
        else:
            bundles.append(pool_exhaustion_trace(tid, base=base))
    return bundles


def mixed_noise_traces(
    n: int = 100, *, start: datetime = BASE, seed: int = 2
) -> list[dict[str, Any]]:
    """Realistic-shape mix: mostly healthy, some anomalies, some
    partial/orphaned traces. The kind of pile a production export
    actually looks like."""
    rng = random.Random(seed)
    bundles: list[dict[str, Any]] = []
    for i in range(n):
        tid = f"mix-{i:05d}"
        base = start + timedelta(milliseconds=i * 200)
        roll = rng.random()
        if roll < 0.65:
            bundles.append(healthy_trace(tid, base=base))
        elif roll < 0.80:
            bundles.append(retry_storm_trace(tid, attempts=rng.choice([2, 3, 5]), base=base))
        elif roll < 0.90:
            bundles.append(downstream_error_trace(tid, base=base))
        elif roll < 0.95:
            bundles.append(pool_exhaustion_trace(tid, base=base))
        else:
            bundles.append(orphan_span_trace(tid, base=base))
    return bundles


# ---------- file writers --------------------------------------------


def write_jsonl(path: Path, bundles: list[dict[str, Any]]) -> None:
    with path.open("w") as fh:
        for b in bundles:
            fh.write(json.dumps(b))
            fh.write("\n")


def write_truncated_jsonl(path: Path, bundles: list[dict[str, Any]]) -> None:
    """Write valid JSONL, then append a truncated JSON line (no newline,
    incomplete syntax). Simulates a writer that died mid-flush."""
    write_jsonl(path, bundles)
    with path.open("a") as fh:
        # Half a JSON object; no terminating newline either.
        fh.write('{"trace_id":"truncated","captured_at":"2026-05-20T09:99')


def _bundle(
    trace_id: str,
    spans: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    *,
    base: datetime,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "captured_at": base.isoformat(),
        "spans": spans,
        "logs": logs,
    }
