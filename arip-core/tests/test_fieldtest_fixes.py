"""Regression tests pinning the field-test-driven fixes.

Each test names the field-test finding it pins (F4–F8). See
arip-fieldtest/FIELDTEST_LOG.md for the original symptoms.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arip_core.canonical.config import NormalizationConfig
from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, Span
from arip_core.engine.abstention import evaluate_abstention
from arip_core.engine.models import Evidence, Hypothesis

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _span(*, span_id: str = "s", parent: str | None = None, service: str = "svc") -> Span:
    return Span(
        trace_id="t",
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        operation_name="op",
        start_time=NOW,
        duration_us=1_000,
        status="OK",
        status_message="",
        attributes={},
        events=[],
    )


def _ct(spans: list[Span]) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=FailureEvent(
            test_name="t", timestamp=NOW, environment="test", trace_id="t",
            assertion="", error_message="",
        ),
        logs=[], spans=spans, k8s_events=[], db_queries=[], timeline=[],
        primary_trace_id="t", related_trace_ids=[], order_id=None,
        normalization_config=NormalizationConfig(),
    )


# ─── F6 — per-rule evidence-kinds floor ──────────────────────────────


def test_default_hypothesis_blocked_with_single_evidence_kind() -> None:
    """Trust contract default: 1 evidence kind → weak_evidence."""
    h = Hypothesis(
        title="t", description="d", confidence=0.9, severity="high",
        evidence=[Evidence(kind="span", description="x")], rule_id="r",
    )
    abst = evaluate_abstention(_ct([_span()]), [h])
    assert abst is not None and abst.code == "weak_evidence"


def test_hypothesis_with_min_evidence_kinds_1_promoted_at_high_confidence() -> None:
    """F6: rules that opt-into single-kind evidence (e.g. latency_vs_db)
    can be promoted past the abstention layer when they're already
    enforcing sharp thresholds. Trust contract preserved by the
    high-confidence requirement."""
    h = Hypothesis(
        title="latency above DB", description="d", confidence=0.85, severity="medium",
        evidence=[Evidence(kind="span", description="x")],
        rule_id="latency_vs_db",
        min_evidence_kinds=1,
    )
    abst = evaluate_abstention(_ct([_span()]), [h])
    assert abst is None, (
        "min_evidence_kinds=1 + confidence above WEAK_CONFIDENCE_CEILING "
        "should pass the abstention gate"
    )


def test_hypothesis_with_min_evidence_kinds_1_still_blocked_when_confidence_weak() -> None:
    """The confidence floor (WEAK_CONFIDENCE_CEILING=0.7) is the OTHER
    half of the trust contract. Opting into single-kind evidence does
    not bypass it."""
    h = Hypothesis(
        title="t", description="d", confidence=0.6, severity="high",
        evidence=[Evidence(kind="span", description="x")],
        rule_id="r",
        min_evidence_kinds=1,
    )
    abst = evaluate_abstention(_ct([_span()]), [h])
    assert abst is not None and abst.code == "weak_evidence"


# ─── F7 — latency_vs_db threshold tightening ─────────────────────────


def test_latency_vs_db_silent_for_typical_healthy_handler() -> None:
    """Pre-fix, the rule fired on any 50ms+ handler with 5ms+ ratio
    DB — which trivially covered healthy auto-instrumented checkout
    handlers (~80-200ms, ~5ms DB). Verify the new floors filter it."""
    from arip_core.engine.rules.latency_vs_db import LatencyVsDBRule

    # 150ms handler (healthy) + 1ms DB → ratio is 150× but
    # handler is below the 200ms absolute floor, so silent.
    handler = Span(
        trace_id="t", span_id="h1", parent_span_id=None,
        service_name="order-service", operation_name="POST /orders",
        start_time=NOW, duration_us=150_000, status="OK", status_message="",
        attributes={}, events=[],
    )
    db = Span(
        trace_id="t", span_id="d1", parent_span_id="h1",
        service_name="order-service", operation_name="db.insert",
        start_time=NOW, duration_us=1_000, status="OK", status_message="",
        attributes={"db.system": "postgresql"}, events=[],
    )
    assert LatencyVsDBRule().evaluate(_ct([handler, db])) == [], (
        "150ms healthy handler must not be flagged as latency anomaly"
    )


def test_latency_vs_db_fires_on_real_world_handler_slow_with_fast_db() -> None:
    """Field test scenario 04: 3000ms handler with 4ms total DB (2 fast
    INSERTs). Previous F7 5ms floor blocked this real-world case."""
    from arip_core.engine.rules.latency_vs_db import LatencyVsDBRule

    handler = Span(
        trace_id="t", span_id="h1", parent_span_id=None,
        service_name="order-service", operation_name="POST /orders",
        start_time=NOW, duration_us=3_000_000,  # 3s handler stall
        status="OK", status_message="",
        attributes={}, events=[],
    )
    db1 = Span(
        trace_id="t", span_id="d1", parent_span_id="h1",
        service_name="order-service", operation_name="db.insert_order",
        start_time=NOW, duration_us=2_500, status="OK", status_message="",
        attributes={"db.system": "postgresql"}, events=[],
    )
    db2 = Span(
        trace_id="t", span_id="d2", parent_span_id="h1",
        service_name="order-service", operation_name="db.update_order",
        start_time=NOW, duration_us=1_500, status="OK", status_message="",
        attributes={"db.system": "postgresql"}, events=[],
    )
    out = LatencyVsDBRule().evaluate(_ct([handler, db1, db2]))
    assert len(out) == 1, "3s handler / 4ms DB should fire (750× ratio)"


# ─── F8 — `arip observe --out` alias ─────────────────────────────────


def test_observe_cli_accepts_out_alias() -> None:
    """`arip observe --out PATH` must work, matching `arip investigate --out`."""
    from arip_core.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["observe", "/tmp/some.jsonl", "--out", "/tmp/digest.md"])
    assert str(ns.digest_out) == "/tmp/digest.md"


def test_observe_cli_digest_out_still_works() -> None:
    """The original flag must remain valid (backwards compat)."""
    from arip_core.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["observe", "/tmp/x.jsonl", "--digest-out", "/tmp/d.md"])
    assert str(ns.digest_out) == "/tmp/d.md"
