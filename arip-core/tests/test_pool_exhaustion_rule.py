"""Unit tests for ``PoolExhaustionRule``.

What this rule must guarantee:

  * Fires when ``db.acquire_connection`` shows pool saturation
    (capacity reached or measurable acquire wait).
  * Does NOT fire on a slow_query signature (handler-level latency,
    no pool stats on a long span).
  * Does NOT fire on a downstream-error signature (no DB spans at all).
  * Abstains (returns ``[]``) when the symptom looks similar but the
    pool-stat attributes are missing.
  * Reads the exact attribute keys emitted by inventory-service:
    db.pool.acquired, db.pool.max, db.pool.wait_ms,
    db.pool.empty_acquires_total.
  * Confidence rises with corroborating evidence (healthy-query span,
    WARN log, non-zero empty_acquires_total).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.engine.rules.pool_exhaustion import PoolExhaustionRule

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


def _failure() -> FailureEvent:
    return FailureEvent(
        test_name="t",
        timestamp=NOW,
        environment="test",
        trace_id="tp",
        assertion="x",
        error_message="boom",
    )


def _ct(spans: list[Span], logs: list[LogEntry] | None = None) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=_failure(),
        logs=logs or [],
        spans=spans,
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="tp",
    )


def _span(
    *,
    op: str,
    service: str = "inventory-service",
    span_id: str = "s",
    parent: str | None = None,
    start_ms: int = 0,
    duration_us: int = 1_000,
    status: str = "OK",
    status_message: str = "",
    attributes: dict | None = None,
    trace_id: str = "tp",
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        operation_name=op,
        start_time=NOW + timedelta(milliseconds=start_ms),
        duration_us=duration_us,
        status=status,
        status_message=status_message,
        attributes=attributes or {},
        events=[],
    )


def _acquire_span(
    *, wait_ms: int, acquired: int, max_conns: int, empties: int = 0, span_id: str = "acq"
) -> Span:
    return _span(
        op="db.acquire_connection",
        span_id=span_id,
        duration_us=wait_ms * 1000,
        attributes={
            "db.system": "postgresql",
            "db.pool.acquired": acquired,
            "db.pool.max": max_conns,
            "db.pool.wait_ms": wait_ms,
            "db.pool.empty_acquires_total": empties,
            "db.pool.idle": max(max_conns - acquired, 0),
            "db.pool.total": max_conns,
        },
    )


def _query_span(*, duration_ms: float = 1.5) -> Span:
    return _span(
        op="db.decrement_stock",
        span_id="q",
        duration_us=int(duration_ms * 1000),
        attributes={
            "db.system": "postgresql",
            "db.operation": "UPDATE",
            "db.sql.table": "inventory",
        },
    )


def _handler_span(*, duration_ms: int, span_id: str = "h") -> Span:
    return _span(
        op="inventory.handle_reserve",
        span_id=span_id,
        duration_us=duration_ms * 1000,
        attributes={"order.id": "ORD-1"},
    )


# --- fires correctly ---------------------------------------------------


def test_fires_on_slow_acquire_with_capacity_at_max():
    spans = [
        _handler_span(duration_ms=1500),
        _acquire_span(wait_ms=1500, acquired=3, max_conns=3, empties=12, span_id="acq1"),
        _query_span(duration_ms=2),
    ]
    out = PoolExhaustionRule().evaluate(_ct(spans))
    assert len(out) == 1
    h = out[0]
    assert h.rule_id == "db_pool_exhaustion"
    assert h.severity == "high"
    # Confidence should pick up the healthy-query contrast.
    assert h.confidence >= 0.85
    descs = " ".join(e.description for e in h.evidence)
    assert "1500ms" in descs
    assert "3/3" in descs
    assert "healthy" in descs.lower()


def test_fires_on_short_wait_when_at_capacity():
    # No wait, but pool is full. Saturation is in-progress.
    spans = [
        _acquire_span(wait_ms=5, acquired=3, max_conns=3, span_id="acq2"),
    ]
    out = PoolExhaustionRule().evaluate(_ct(spans))
    assert len(out) == 1


def test_fires_when_only_wait_signal_present():
    # Pool below capacity at sample time but a measurable wait happened
    # — typical right after a victim was unblocked.
    spans = [
        _acquire_span(wait_ms=300, acquired=2, max_conns=3, span_id="acq3"),
    ]
    out = PoolExhaustionRule().evaluate(_ct(spans))
    assert len(out) == 1


# --- abstains correctly ----------------------------------------------


def test_silent_when_no_pool_attributes_present():
    # A slow db span without any pool stats — could be a slow query,
    # could be many things. This rule MUST not guess.
    spans = [
        _handler_span(duration_ms=1500),
        _span(
            op="db.acquire_connection",
            span_id="ghost",
            duration_us=1_500_000,
            attributes={"db.system": "postgresql"},  # NO db.pool.*
        ),
    ]
    assert PoolExhaustionRule().evaluate(_ct(spans)) == []


def test_silent_below_saturation_thresholds():
    # Below capacity, near-zero wait — healthy pool.
    spans = [
        _acquire_span(wait_ms=3, acquired=1, max_conns=3, span_id="acq4"),
        _query_span(duration_ms=2),
    ]
    assert PoolExhaustionRule().evaluate(_ct(spans)) == []


def test_silent_on_slow_query_signature():
    # slow_query injection: handler is slow but DB spans are fast and
    # there are NO pool stats anywhere.
    spans = [
        _handler_span(duration_ms=305),
        _query_span(duration_ms=2),
    ]
    assert PoolExhaustionRule().evaluate(_ct(spans)) == []


def test_silent_on_downstream_error_signature():
    # downstream_error injection: HTTP 500 error chain, no DB activity.
    spans = [
        _span(op="HTTP POST", service="payment-service", span_id="p1", status="ERROR"),
        _span(op="inventory.handle_reserve", span_id="i1", parent="p1", status="ERROR"),
    ]
    assert PoolExhaustionRule().evaluate(_ct(spans)) == []


# --- confidence rises with corroborating evidence ------------------


def test_confidence_increases_with_warn_log():
    spans = [
        _handler_span(duration_ms=1500),
        _acquire_span(wait_ms=1500, acquired=3, max_conns=3, empties=12, span_id="acq5"),
        _query_span(duration_ms=2),
    ]
    no_log = PoolExhaustionRule().evaluate(_ct(spans))[0]

    log = LogEntry(
        timestamp=NOW,
        service_name="inventory",
        level="WARN",
        message="slow db connection acquire",
        trace_id="tp",
        fields={"wait_ms": 1502, "pool_acquired": 3, "pool_max": 3},
    )
    with_log = PoolExhaustionRule().evaluate(_ct(spans, logs=[log]))[0]
    assert with_log.confidence > no_log.confidence
    assert any(e.kind == "log" for e in with_log.evidence)


# --- determinism ----------------------------------------------------


def test_rule_is_deterministic():
    spans = [
        _handler_span(duration_ms=1500),
        _acquire_span(wait_ms=1500, acquired=3, max_conns=3, empties=12, span_id="acq6"),
        _query_span(duration_ms=2),
    ]
    ct = _ct(spans)
    a = PoolExhaustionRule().evaluate(ct)
    b = PoolExhaustionRule().evaluate(ct)
    assert [h.title for h in a] == [h.title for h in b]
    assert [h.confidence for h in a] == [h.confidence for h in b]
