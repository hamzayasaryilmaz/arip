"""Tests for evidence integrity auditing.

The auditor drops evidence that cites references nowhere in the
telemetry, decays confidence accordingly, and drops hypotheses left
with no surviving evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.engine.evidence_audit import audit_and_clean
from arip_core.engine.models import Evidence, Hypothesis

NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def _failure() -> FailureEvent:
    return FailureEvent(
        test_name="t", timestamp=NOW, environment="test",
        trace_id="tp", assertion="x", error_message="boom",
    )


def _span(trace_id="tp", span_id="s1") -> Span:
    return Span(
        trace_id=trace_id, span_id=span_id, parent_span_id=None,
        service_name="payment-service", operation_name="op",
        start_time=NOW, duration_us=1, status="OK", status_message="",
        attributes={}, events=[],
    )


def _ct(spans=None, logs=None) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=_failure(),
        logs=logs or [],
        spans=spans or [_span()],
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="tp",
    )


def test_keeps_well_grounded_evidence():
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high", rule_id="r",
        evidence=[Evidence(kind="span", description="x", trace_id="tp", span_id="s1", service="x")],
    )
    out = audit_and_clean(_ct(), [h])
    assert len(out) == 1
    assert out[0].confidence == 0.9
    assert len(out[0].evidence) == 1


def test_drops_evidence_with_unknown_span_id():
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high", rule_id="r",
        evidence=[
            Evidence(kind="span", description="ok", trace_id="tp", span_id="s1"),
            Evidence(kind="span", description="ghost", trace_id="tp", span_id="DOES-NOT-EXIST"),
        ],
    )
    out = audit_and_clean(_ct(), [h])
    assert len(out) == 1
    assert len(out[0].evidence) == 1
    assert out[0].evidence[0].description == "ok"
    assert out[0].confidence < 0.9  # decayed


def test_drops_hypothesis_when_all_evidence_ungrounded():
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high", rule_id="r",
        evidence=[
            Evidence(kind="span", description="ghost1", trace_id="other-trace", span_id="x"),
            Evidence(kind="span", description="ghost2", trace_id="tp", span_id="missing"),
        ],
    )
    assert audit_and_clean(_ct(), [h]) == []


def test_keeps_log_evidence_when_log_matches():
    log = LogEntry(
        timestamp=NOW, service_name="payment", level="WARN",
        message="webhook arrived early", trace_id="tp", fields={},
    )
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high", rule_id="r",
        evidence=[Evidence(kind="log", description="payment: webhook arrived early", service="payment")],
    )
    out = audit_and_clean(_ct(logs=[log]), [h])
    assert len(out) == 1


def test_drops_log_evidence_with_unknown_message():
    log = LogEntry(
        timestamp=NOW, service_name="payment", level="WARN",
        message="something else", trace_id="tp", fields={},
    )
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high", rule_id="r",
        evidence=[Evidence(kind="log", description="payment: hallucinated message", service="payment")],
    )
    assert audit_and_clean(_ct(logs=[log]), [h]) == []
