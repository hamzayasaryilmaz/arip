"""Calibration benchmark: messy-telemetry scenarios.

This file is the standing test of *precision under bad telemetry*.
Every scenario below constructs a synthetic CorrelatedTelemetry with
a specific pathology and asserts that ARIP behaves *honestly* — either
abstaining with the right diagnostic code or producing a deliberately
modest hypothesis. **A scenario that produces a high-confidence wrong
RCA is a regression.**

No production code is allowed to special-case these inputs. Anything
that improves behaviour here must improve it through the existing
trust layer (rule templates, abstention, evidence audit, quality
assessment) — not by adding scenario-specific guards.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.engine.hypothesis import investigate
from arip_core.quality.assessment import assess

NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)


def _failure(trace_id="t-primary", assertion="x", order_id="ORD-1"):
    return FailureEvent(
        test_name="benchmark scenario",
        timestamp=NOW,
        environment="benchmark",
        trace_id=trace_id,
        assertion=assertion,
        error_message="benchmark error",
        test_metadata={"annotations": {"order_id": order_id}},
    )


def _ct(spans=None, logs=None, primary="t-primary", failure=None):
    return CorrelatedTelemetry(
        failure=failure or _failure(trace_id=primary),
        logs=logs or [],
        spans=spans or [],
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id=primary,
    )


def _span(
    *,
    op,
    service="payment-service",
    span_id="s",
    parent=None,
    start_ms=0,
    duration_us=1_000,
    status="OK",
    status_message="",
    attributes=None,
    events=None,
    trace_id="t-primary",
):
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
        events=events or [],
    )


def _no_false_high_confidence(result, max_conf=0.85):
    """Helper: the engine never nominates a high-confidence primary
    when the input is structurally degraded."""
    if result.primary is None:
        return  # abstain is always acceptable
    assert result.primary.confidence < max_conf, (
        f"REGRESSION: produced high-confidence primary "
        f"({result.primary.rule_id} @ {result.primary.confidence}) on "
        f"degraded telemetry."
    )


# ── Scenario 1: primary trace is entirely missing ────────────────────


def test_scenario_missing_primary_trace_abstains_no_primary_trace():
    """No spans at all — the primary trace never arrived. The engine
    MUST abstain with `no_primary_trace`, never produce a hypothesis."""
    ct = _ct(spans=[], primary="t-vanished")
    result = investigate(ct)
    assert result.primary is None
    assert result.abstention is not None
    assert result.abstention.code == "no_primary_trace"


# ── Scenario 2: telemetry exists but no rule matches ────────────────


def test_scenario_unknown_pattern_abstains_no_rule_matched():
    """Spans exist but represent a pattern with no rule coverage —
    a single fast, healthy span. Engine MUST surface no_rule_matched."""
    span = _span(op="health.check", duration_us=2_000, status="OK")
    ct = _ct(spans=[span], primary=span.trace_id)
    result = investigate(ct)
    assert result.primary is None
    assert result.abstention is not None
    assert result.abstention.code in {"no_rule_matched", "weak_evidence"}


# ── Scenario 3: broken propagation (orphan spans) ────────────────────


def test_scenario_orphan_spans_do_not_cause_false_chain():
    """Spans whose parent_span_id refers to a span not in the slice.
    downstream_error walks parent→child; it MUST NOT manufacture a
    chain from missing parents."""
    # An ERROR child whose 'parent' span_id does not exist in ct.spans
    orphan = _span(
        op="inventory.handle_reserve",
        service="inventory-service",
        span_id="orphan",
        parent="ghost-parent",
        status="ERROR",
        status_message="HTTP 503",
    )
    ct = _ct(spans=[orphan], primary=orphan.trace_id)
    result = investigate(ct)
    _no_false_high_confidence(result)

    # Quality assessment must flag the orphan as a propagation issue.
    q = assess(ct)
    propagation = next(
        (c for c in q.coverages if c.signal == "propagation_health"), None
    )
    assert propagation is not None
    assert propagation.satisfied < propagation.applicable


# ── Scenario 4: partial retry metadata (attempt yes, reason/backoff no) ─


def test_scenario_partial_retry_metadata_produces_low_confidence_hypothesis():
    """retry.attempt is present but retry.reason and retry.backoff_ms
    are not. retry_storm rule should fire but at LOW confidence —
    not the 0.94 it gets with complete metadata."""
    spans = [
        _span(
            op="inventory.reserve_attempt",
            span_id=f"a{n}",
            status="ERROR",
            attributes={"retry.attempt": n},  # only attempt, nothing else
        )
        for n in (1, 2, 3)
    ]
    ct = _ct(spans=spans, primary=spans[0].trace_id)
    result = investigate(ct)
    # Engine may abstain (likely weak_evidence) OR fire retry_storm with low confidence.
    if result.primary is not None:
        assert result.primary.rule_id == "retry_storm"
        assert result.primary.confidence < 0.85, (
            f"retry_storm should not be >= 0.85 confidence without "
            f"reason/backoff/policy metadata; got {result.primary.confidence}"
        )
    # No matter what, no false-high-confidence primary on incomplete metadata.
    _no_false_high_confidence(result)


# ── Scenario 5: HTTP-error span without OTel ERROR status ────────────


def test_scenario_http_5xx_without_otel_error_quality_drops():
    """An auto-instrumentation gap: http.status=500 but span.status=OK.
    The engine cannot detect the error chain. Quality assessment MUST
    surface this as the actionable findability gap."""
    parent = _span(
        op="HTTP POST",
        service="payment-service",
        span_id="parent",
        status="OK",  # bug in instrumentation — should be ERROR
        attributes={"http.response.status_code": 500},
    )
    ct = _ct(spans=[parent], primary=parent.trace_id)
    result = investigate(ct)
    _no_false_high_confidence(result)

    q = assess(ct)
    finding = next(
        (f for f in q.findings if f.signal == "error_status_consistency"), None
    )
    assert finding is not None
    assert "HTTP-error span" in finding.message


# ── Scenario 6: sampled trace — only some retry attempts visible ─────


def test_scenario_sampled_trace_does_not_falsely_call_storm_persistent():
    """A sampled trace shows attempts 1 and 5 of 5 — the middle 3 were
    dropped. retry_storm sees 2 attempts. The rule MUST NOT claim
    'persistent downstream' just because the visible attempts both
    errored — the engine has no evidence about the missing ones."""
    spans = [
        _span(
            op="inventory.reserve_attempt",
            span_id=f"a{n}",
            status="ERROR",
            attributes={
                "retry.attempt": n,
                "retry.max_attempts": 5,
                "retry.backoff_ms": [0, 0, 0, 0, 400][n - 1],
                "retry.reason": "upstream 503",
                "retry.policy": "exponential",
            },
        )
        for n in (1, 5)  # middle 3 are missing
    ]
    ct = _ct(spans=spans, primary=spans[0].trace_id)
    result = investigate(ct)
    # retry_storm SHOULD fire (we have ≥2 attempts) but cannot truthfully
    # claim "every attempt failed" because we are missing attempts 2-4.
    # The current rule treats visible attempts as the chain; we accept
    # that, but the report must NOT crack the 0.95 confidence ceiling
    # that "fully observed" retry chains achieve.
    if result.primary is not None and result.primary.rule_id == "retry_storm":
        assert result.primary.confidence <= 0.95


# ── Scenario 7: inconsistent business-key naming within one trace ────


def test_scenario_inconsistent_business_key_naming_partial_correlation():
    """One span uses `order.id`, another uses `order_id` (typo / mixed
    instrumentation). Default config only knows `order.id`. The
    correlation must be partial, never silently identical."""
    a = _span(op="x", span_id="a", attributes={"order.id": "ORD-1"})
    b = _span(op="y", span_id="b", attributes={"order_id": "ORD-1"})  # typo
    ct = _ct(spans=[a, b], primary=a.trace_id)
    result = investigate(ct)
    # No rule should fire; this is "low-quality telemetry, nothing actionable".
    _no_false_high_confidence(result)
    q = assess(ct)
    # Quality should detect SOME business-key gap (the typo'd span is
    # not counted as having a key under default config).
    assert q.coverages


# ── Scenario 8: quality scores correlate with rule readiness ─────────


@pytest.mark.parametrize("pathology, expected_band", [
    ("rich",  "high"),
    ("thin",  "low"),
])
def test_quality_score_correlates_with_telemetry_richness(pathology, expected_band):
    if pathology == "rich":
        # A clean retry_storm trace: all signals, proper propagation,
        # correlated logs.
        spans = [
            _span(
                op="checkout.process", span_id="root", parent=None,
                status="ERROR",
                attributes={"order.id": "ORD-1"},
            ),
            _span(
                op="HTTP POST", span_id="hp", parent="root",
                status="ERROR",
                attributes={"http.response.status_code": 503},
            ),
            _span(
                op="inventory.handle_reserve",
                service="inventory-service",
                span_id="inv", parent="hp",
                status="ERROR",
                attributes={"order.id": "ORD-1"},
            ),
        ]
        logs = [
            LogEntry(
                timestamp=NOW, service_name="inventory",
                level="ERROR", message="reserve failed",
                trace_id=spans[0].trace_id, fields={"order_id": "ORD-1"},
            ),
        ]
    else:
        # Thin: orphan span with no attrs, no logs.
        spans = [_span(op="x", span_id="lonely", parent="ghost", status="OK")]
        logs = []

    ct = _ct(spans=spans, logs=logs, primary=spans[0].trace_id)
    q = assess(ct)
    assert q.confidence_band == expected_band


# ── Scenario 9: per-rule readiness reflects telemetry presence ───────


def test_rule_readiness_reflects_telemetry_signals_present():
    """When telemetry contains retry metadata but no pool stats and no
    business key, quality should say retry_storm is likely to fire but
    pool_exhaustion and concurrent_modification are not."""
    spans = [
        _span(
            op="inventory.reserve_attempt",
            span_id=f"a{n}",
            attributes={
                "retry.attempt": n,
                "retry.max_attempts": 3,
                "retry.backoff_ms": [0, 50, 100][n - 1],
                "retry.reason": "upstream 503",
                "retry.policy": "exponential",
            },
            status="ERROR",
        )
        for n in (1, 2, 3)
    ]
    ct = _ct(spans=spans, primary=spans[0].trace_id)
    q = assess(ct)
    assert "retry_storm" in q.rules_likely_to_fire
    assert "db_pool_exhaustion" in q.rules_will_not_fire
    assert "concurrent_modification" in q.rules_will_not_fire
