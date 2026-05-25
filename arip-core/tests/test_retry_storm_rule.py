"""Unit tests for ``RetryStormRule``.

Guarantees the rule must hold:

  * Fires when 2+ same-operation attempts in one trace carry
    ``retry.attempt`` metadata.
  * Stays silent on a single-attempt trace (no storm) even if it
    errors — that's downstream_error territory, not retry_storm.
  * Stays silent when ``retry.*`` metadata is entirely absent —
    abstention via "no signature match".
  * Stays silent on the pool_exhaustion signature (no retry.attempt).
  * Confidence rises with corroborating evidence: consistent retry
    reason, exponential backoff, exhausted budget, ERROR logs.
  * Deterministic: same input → same output.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.engine.rules.retry_storm import RetryStormRule

# re-exported for tests below
__all__ = ["Span"]

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


def _failure() -> FailureEvent:
    return FailureEvent(
        test_name="t", timestamp=NOW, environment="test",
        trace_id="tp", assertion="x", error_message="boom",
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
    service: str = "payment-service",
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


def _attempt(
    *,
    n: int,
    backoff_ms: int,
    reason: str = "upstream 503: service temporarily unavailable",
    status: str = "ERROR",
    op: str = "inventory.reserve_attempt",
    start_ms: int | None = None,
) -> Span:
    return _span(
        op=op,
        span_id=f"a{n}",
        start_ms=start_ms if start_ms is not None else (backoff_ms + 5) * (n - 1),
        duration_us=3_000,
        status=status,
        status_message=reason if status == "ERROR" else "",
        attributes={
            "retry.attempt": n,
            "retry.max_attempts": 5,
            "retry.backoff_ms": backoff_ms,
            "retry.policy": "exponential",
            "retry.reason": reason,
            "retry.retriable": True,
        },
    )


# --- fires correctly --------------------------------------------------


def test_fires_on_five_attempts_with_exponential_backoff():
    spans = [
        _attempt(n=1, backoff_ms=0),
        _attempt(n=2, backoff_ms=50),
        _attempt(n=3, backoff_ms=100),
        _attempt(n=4, backoff_ms=200),
        _attempt(n=5, backoff_ms=400),
    ]
    out = RetryStormRule().evaluate(_ct(spans))
    assert len(out) == 1
    h = out[0]
    assert h.rule_id == "retry_storm"
    assert h.severity == "high"
    # 5 attempts × good signal → high confidence
    assert h.confidence >= 0.88
    assert "5 attempts" in h.title
    # All attempts cited
    span_evidence = [e for e in h.evidence if e.kind == "span" and "attempt" in e.description]
    assert len(span_evidence) == 5
    # Description mentions exponential and amplification
    assert "exponential" in h.description.lower()
    assert "5×" in h.description or "5x" in h.description.lower()


def test_fires_on_two_attempts_minimum():
    spans = [
        _attempt(n=1, backoff_ms=0),
        _attempt(n=2, backoff_ms=50),
    ]
    out = RetryStormRule().evaluate(_ct(spans))
    assert len(out) == 1


# --- stays silent / abstains ----------------------------------------


def test_silent_on_single_attempt():
    # One attempt, even with retry metadata, is not a storm.
    spans = [_attempt(n=1, backoff_ms=0)]
    assert RetryStormRule().evaluate(_ct(spans)) == []


def test_silent_without_retry_metadata():
    # Downstream error with no retry telemetry at all — retry storm
    # rule must NOT speculate.
    spans = [
        _span(op="HTTP POST", span_id="p", status="ERROR"),
        _span(
            op="inventory.handle_reserve",
            service="inventory-service",
            span_id="i",
            parent="p",
            status="ERROR",
            status_message="internal error",
        ),
    ]
    assert RetryStormRule().evaluate(_ct(spans)) == []


def test_silent_on_pool_exhaustion_signature():
    # The pool_exhaustion signature has db.pool.* attributes but
    # no retry.attempt. The retry storm rule must not fire here.
    spans = [
        _span(
            op="db.acquire_connection",
            service="inventory-service",
            span_id="acq",
            duration_us=1_500_000,
            attributes={
                "db.system": "postgresql",
                "db.pool.acquired": 3,
                "db.pool.max": 3,
                "db.pool.wait_ms": 1500,
            },
        ),
    ]
    assert RetryStormRule().evaluate(_ct(spans)) == []


def test_silent_when_attempts_in_different_operations():
    # Two spans with retry.attempt, but on different operations —
    # not the same chain, so not a storm by definition.
    spans = [
        _span(
            op="inventory.reserve_attempt",
            span_id="a",
            attributes={"retry.attempt": 1, "retry.max_attempts": 5,
                        "retry.backoff_ms": 0, "retry.policy": "exponential"},
        ),
        _span(
            op="auth.verify_attempt",
            span_id="b",
            attributes={"retry.attempt": 1, "retry.max_attempts": 5,
                        "retry.backoff_ms": 0, "retry.policy": "exponential"},
        ),
    ]
    assert RetryStormRule().evaluate(_ct(spans)) == []


# --- confidence rises with corroboration ----------------------------


def test_confidence_increases_with_consistent_reason_and_exponential():
    weak = [
        # Two attempts, varying reason, non-exponential
        _attempt(n=1, backoff_ms=0, reason="reason A"),
        _attempt(n=2, backoff_ms=10, reason="reason B"),
    ]
    strong = [
        _attempt(n=1, backoff_ms=0),
        _attempt(n=2, backoff_ms=50),
        _attempt(n=3, backoff_ms=100),
        _attempt(n=4, backoff_ms=200),
        _attempt(n=5, backoff_ms=400),
    ]
    w = RetryStormRule().evaluate(_ct(weak))[0]
    s = RetryStormRule().evaluate(_ct(strong))[0]
    assert s.confidence > w.confidence


def test_confidence_increases_with_error_log():
    spans = [_attempt(n=1, backoff_ms=0), _attempt(n=2, backoff_ms=50)]
    no_log = RetryStormRule().evaluate(_ct(spans))[0]
    log = LogEntry(
        timestamp=NOW, service_name="inventory", level="ERROR",
        message="reserve failed", trace_id="tp",
        fields={"error": "service temporarily unavailable"},
    )
    with_log = RetryStormRule().evaluate(_ct(spans, logs=[log]))[0]
    assert with_log.confidence > no_log.confidence


def test_confidence_increases_when_budget_exhausted():
    # Two attempts (not exhausted) vs five attempts (exhausted at 5/5).
    short = [_attempt(n=1, backoff_ms=0), _attempt(n=2, backoff_ms=50)]
    long = [
        _attempt(n=1, backoff_ms=0),
        _attempt(n=2, backoff_ms=50),
        _attempt(n=3, backoff_ms=100),
        _attempt(n=4, backoff_ms=200),
        _attempt(n=5, backoff_ms=400),
    ]
    s = RetryStormRule().evaluate(_ct(short))[0]
    l = RetryStormRule().evaluate(_ct(long))[0]
    assert l.confidence > s.confidence


# --- determinism ---------------------------------------------------


def test_partial_failure_does_not_claim_persistent():
    """Hardening regression: if any attempt OKs, the rule must not say
    'every attempt failed with the same reason' or 'persistent downstream'."""
    spans = [
        _attempt(n=1, backoff_ms=0, status="ERROR"),
        # second attempt: success, no retry.reason, no ERROR status
        Span(
            trace_id="tp", span_id="a2", parent_span_id=None,
            service_name="payment-service", operation_name="inventory.reserve_attempt",
            start_time=NOW, duration_us=3_000,
            status="OK", status_message="",
            attributes={
                "retry.attempt": 2,
                "retry.max_attempts": 5,
                "retry.backoff_ms": 50,
                "retry.policy": "exponential",
                # NO retry.reason — success path
            },
            events=[],
        ),
    ]
    out = RetryStormRule().evaluate(_ct(spans))
    assert len(out) == 1
    h = out[0]
    desc = h.description.lower()
    # Must NOT make the strong "persistent" or "every attempt" claim
    assert "persistent downstream" not in desc
    assert "every attempt failed" not in desc
    # Must acknowledge recovery
    assert "recovered" in desc or "transient" in desc
    # Per-attempt evidence: when only 1 of N errored, do not claim
    # "Each of the N attempts hit ERROR".
    span_evidence = " ".join(e.description for e in h.evidence)
    assert "each of the" not in span_evidence.lower()


def test_rule_is_deterministic():
    spans = [
        _attempt(n=1, backoff_ms=0),
        _attempt(n=2, backoff_ms=50),
        _attempt(n=3, backoff_ms=100),
    ]
    ct = _ct(spans)
    a = RetryStormRule().evaluate(ct)
    b = RetryStormRule().evaluate(ct)
    assert [h.title for h in a] == [h.title for h in b]
    assert [h.confidence for h in a] == [h.confidence for h in b]
