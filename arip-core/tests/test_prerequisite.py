"""Tests for the telemetry prerequisite gate.

The prereq gate runs BEFORE the engine touches anything. Its job
is to refuse to investigate when the telemetry source isn't
distributed-tracing-shaped, so ARIP never produces plausible-
looking nonsense from logs-only or single-service-only data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arip_core.canonical.config import NormalizationConfig
from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, Span
from arip_core.quality.prerequisite import (
    check_prerequisites,
)

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _failure(trace_id: str = "t-pre") -> FailureEvent:
    return FailureEvent(
        test_name="t",
        timestamp=NOW,
        environment="test",
        trace_id=trace_id,
        assertion="",
        error_message="",
    )


def _span(
    *,
    trace_id: str = "t-pre",
    span_id: str = "s1",
    parent: str | None = None,
    service: str = "svc",
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        operation_name="op",
        start_time=NOW,
        duration_us=1000,
        status="OK",
        status_message="",
        attributes={},
        events=[],
    )


def _ct(spans: list[Span]) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=_failure(),
        logs=[],
        spans=spans,
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="t-pre",
        related_trace_ids=[],
        order_id=None,
        normalization_config=NormalizationConfig(),
    )


# ---------- failure cases (gate fires) ---------------------------


def test_fails_on_no_spans() -> None:
    failure = check_prerequisites(_ct([]))
    assert failure is not None
    assert failure.code == "no_spans"
    assert "OpenTelemetry-shaped spans" in failure.detail
    assert failure.next_step  # always non-empty


def test_fails_on_no_trace_id() -> None:
    failure = check_prerequisites(_ct([_span(trace_id="")]))
    assert failure is not None
    assert failure.code == "no_trace_id"
    assert "trace_id" in failure.detail


def test_fails_on_no_propagation_single_service_no_chain() -> None:
    """1 span, 1 service, no parent_span_id → no propagation."""
    failure = check_prerequisites(_ct([_span()]))
    assert failure is not None
    assert failure.code == "no_propagation"
    assert "1 service" in failure.detail or "one service" in failure.detail.lower()


def test_fails_on_orphan_chain_single_service() -> None:
    """Parent_span_id references a span not in the bundle → not a chain."""
    spans = [_span(span_id="child", parent="missing")]
    failure = check_prerequisites(_ct(spans))
    assert failure is not None
    assert failure.code == "no_propagation"


# ---------- success cases (gate passes) --------------------------


def test_passes_with_two_services() -> None:
    """Multi-service → distributed context present even without parent chain."""
    spans = [_span(span_id="a", service="svc-a"), _span(span_id="b", service="svc-b")]
    assert check_prerequisites(_ct(spans)) is None


def test_passes_with_in_service_parent_chain() -> None:
    """Single-service but parent_span_id resolves within bundle → valid tree."""
    spans = [
        _span(span_id="root"),
        _span(span_id="child", parent="root"),
    ]
    assert check_prerequisites(_ct(spans)) is None


def test_passes_with_full_multi_service_tree() -> None:
    spans = [
        _span(span_id="r", service="frontend"),
        _span(span_id="c1", parent="r", service="cart"),
        _span(span_id="c2", parent="c1", service="db"),
    ]
    assert check_prerequisites(_ct(spans)) is None


# ---------- next_step is always actionable -----------------------


def test_every_failure_has_actionable_next_step() -> None:
    """Operator should always know what to do next when gate fires."""
    for ct_input in [
        _ct([]),
        _ct([_span(trace_id="")]),
        _ct([_span()]),
    ]:
        f = check_prerequisites(ct_input)
        assert f is not None
        assert f.next_step
        assert len(f.next_step) > 50  # actually a sentence, not a stub
        assert "docs/" in f.next_step or "see " in f.next_step.lower()
