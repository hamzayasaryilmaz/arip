"""Unit tests for the deterministic investigation rules.

Each test feeds a hand-crafted ``CorrelatedTelemetry`` to one rule and
checks the shape of the hypotheses that come out. No Jaeger, no Docker.

Important: fixtures here use only "natural" telemetry the
applications would produce in production — span timing, span events
named ``state.transition``, business attributes like ``order.id``,
WARN log lines. They do NOT use any pre-classified "anomaly.X"
markers, because the rules under test must not depend on those.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.engine.rules.downstream_error import DownstreamErrorRule
from arip_core.engine.rules.latency_vs_db import LatencyVsDBRule
from arip_core.engine.rules.webhook_race import WebhookRaceRule

NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


def _failure(trace_id: str = "t-primary", order_id: str = "ORD-1") -> FailureEvent:
    return FailureEvent(
        test_name="t",
        timestamp=NOW,
        environment="test",
        trace_id=trace_id,
        assertion="x",
        error_message="boom",
        test_metadata={"annotations": {"order_id": order_id}},
    )


def _ct(
    spans: list[Span],
    logs: list[LogEntry] | None = None,
    order_id: str = "ORD-1",
) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=_failure(order_id=order_id),
        logs=logs or [],
        spans=spans,
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="t-primary",
        related_trace_ids=[],
        order_id=order_id,
    )


def _span(
    *,
    op: str,
    svc: str = "payment-service",
    span_id: str = "s1",
    parent: str | None = None,
    start_ms: int = 0,
    duration_us: int = 1_000,
    status: str = "OK",
    status_message: str = "",
    attributes: dict | None = None,
    events: list[dict] | None = None,
    trace_id: str = "t-primary",
) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service_name=svc,
        operation_name=op,
        start_time=NOW + timedelta(milliseconds=start_ms),
        duration_us=duration_us,
        status=status,
        status_message=status_message,
        attributes=attributes or {},
        events=events or [],
    )


def _transition_event(ms: int, frm: str, to: str, order_id: str = "ORD-1") -> dict:
    return {
        "timestamp": NOW + timedelta(milliseconds=ms),
        "fields": {
            "event": "state.transition",
            "state.from": frm,
            "state.to": to,
            "order.id": order_id,
        },
    }


# --- WebhookRaceRule: concurrent_modification ----------------------------


def test_concurrent_modification_fires_when_traces_overlap_and_both_transition():
    # Outer (long) trace: checkout.process from 0..300ms, transitions pending → confirmed
    outer = _span(
        op="checkout.process",
        trace_id="t-checkout",
        span_id="s-co",
        start_ms=0,
        duration_us=300_000,
        attributes={"order.id": "ORD-1"},
        events=[
            _transition_event(0, "", "pending"),
            _transition_event(300, "pending", "confirmed"),
        ],
    )
    # Inner (short) trace: webhook.process from 50..51ms, transitions pending → paid
    inner = _span(
        op="webhook.process",
        trace_id="t-webhook",
        span_id="s-wh",
        start_ms=50,
        duration_us=1_000,
        attributes={"order.id": "ORD-1"},
        events=[_transition_event(50, "pending", "paid")],
    )
    out = WebhookRaceRule().evaluate(_ct([outer, inner]))
    assert len(out) == 1
    h = out[0]
    assert h.severity == "high"
    assert h.confidence >= 0.8
    assert h.rule_id == "concurrent_modification"
    # Cites both traces and at least one state transition.
    trace_ids = {ev.trace_id for ev in h.evidence if ev.trace_id}
    assert {"t-checkout", "t-webhook"} <= trace_ids
    assert any(ev.kind == "span_event" for ev in h.evidence)


def test_concurrent_modification_silent_when_no_time_overlap():
    a = _span(
        op="checkout.process",
        trace_id="t-a",
        span_id="s-a",
        start_ms=0,
        duration_us=10_000,
        attributes={"order.id": "ORD-1"},
        events=[_transition_event(0, "", "pending"), _transition_event(10, "pending", "confirmed")],
    )
    b = _span(
        op="webhook.process",
        trace_id="t-b",
        span_id="s-b",
        start_ms=500,
        duration_us=1_000,
        attributes={"order.id": "ORD-1"},
        events=[_transition_event(500, "confirmed", "paid")],
    )
    assert WebhookRaceRule().evaluate(_ct([a, b])) == []


def test_concurrent_modification_silent_when_only_one_trace_transitions():
    # Both traces touch the order and overlap in time, but only one
    # actually mutated state — the other might just be a read. The rule
    # should NOT fire on read/write overlap, only on write/write.
    writer = _span(
        op="checkout.process",
        trace_id="t-a",
        span_id="s-a",
        start_ms=0,
        duration_us=300_000,
        attributes={"order.id": "ORD-1"},
        events=[
            _transition_event(0, "", "pending"),
            _transition_event(300, "pending", "confirmed"),
        ],
    )
    reader = _span(
        op="order.lookup",
        trace_id="t-b",
        span_id="s-b",
        start_ms=50,
        duration_us=1_000,
        attributes={"order.id": "ORD-1"},
        # no state.transition events
    )
    assert WebhookRaceRule().evaluate(_ct([writer, reader])) == []


def test_concurrent_modification_confidence_rises_with_warn_log():
    outer = _span(
        op="checkout.process",
        trace_id="t-checkout",
        span_id="s-co",
        start_ms=0,
        duration_us=300_000,
        attributes={"order.id": "ORD-1"},
        events=[
            _transition_event(0, "", "pending"),
            _transition_event(300, "pending", "confirmed"),
        ],
    )
    inner = _span(
        op="webhook.process",
        trace_id="t-webhook",
        span_id="s-wh",
        start_ms=50,
        duration_us=1_000,
        attributes={"order.id": "ORD-1"},
        events=[_transition_event(50, "pending", "paid")],
    )
    warn_log = LogEntry(
        timestamp=NOW + timedelta(milliseconds=300),
        service_name="payment",
        level="WARN",
        message="order in unexpected state during confirmation",
        trace_id="t-checkout",
        fields={"order_id": "ORD-1", "actual_previous": "paid"},
    )
    no_warn = WebhookRaceRule().evaluate(_ct([outer, inner]))
    with_warn = WebhookRaceRule().evaluate(_ct([outer, inner], logs=[warn_log]))
    assert with_warn[0].confidence > no_warn[0].confidence


def test_concurrent_modification_silent_for_single_trace():
    only_one = _span(
        op="checkout.process",
        trace_id="t-a",
        span_id="s-a",
        start_ms=0,
        duration_us=300_000,
        attributes={"order.id": "ORD-1"},
        events=[
            _transition_event(0, "", "pending"),
            _transition_event(300, "pending", "confirmed"),
        ],
    )
    assert WebhookRaceRule().evaluate(_ct([only_one])) == []


# --- DownstreamErrorRule -----------------------------------------------


def test_downstream_error_finds_cross_service_chain():
    parent = _span(
        op="HTTP POST",
        svc="payment-service",
        span_id="p1",
        status="ERROR",
        status_message="bad gateway",
    )
    child = _span(
        op="inventory.handle_reserve",
        svc="inventory-service",
        span_id="i1",
        parent="p1",
        status="ERROR",
        status_message="internal error",
    )
    out = DownstreamErrorRule().evaluate(_ct([parent, child]))
    assert len(out) == 1
    h = out[0]
    assert "inventory-service" in h.title
    assert h.severity == "high"


def test_downstream_error_ignores_same_service_chain():
    parent = _span(op="a", svc="payment-service", span_id="a", status="ERROR")
    child = _span(op="b", svc="payment-service", span_id="b", parent="a", status="ERROR")
    assert DownstreamErrorRule().evaluate(_ct([parent, child])) == []


def test_downstream_error_silent_when_no_error():
    parent = _span(op="a", span_id="a")
    child = _span(op="b", span_id="b", parent="a")
    assert DownstreamErrorRule().evaluate(_ct([parent, child])) == []


def test_downstream_error_softens_claim_when_chain_not_fully_propagated():
    """Hardening regression: the rule must NOT claim 'every span above is
    ERROR' when ancestors above the immediate error parent are OK."""
    # The error chain stops at the HTTP POST span; the grandparent is OK
    # (e.g. retry recovered the request).
    root = _span(op="checkout.process", span_id="root", status="OK")
    http_post = _span(
        op="HTTP POST",
        svc="payment-service",
        span_id="hp",
        parent="root",
        status="ERROR",
    )
    inv = _span(
        op="inventory.handle_reserve",
        svc="inventory-service",
        span_id="inv",
        parent="hp",
        status="ERROR",
        status_message="HTTP 503",
    )
    out = DownstreamErrorRule().evaluate(_ct([root, http_post, inv]))
    assert len(out) == 1
    h = out[0]
    # Must NOT make the strong claim
    assert "every span above" not in h.description.lower()
    # Should explicitly acknowledge recovery
    assert "recovered" in h.description.lower() or "localised" in h.description.lower()
    # Confidence drops below the fully-propagated baseline
    assert h.confidence < 0.9


# --- LatencyVsDBRule ---------------------------------------------------


def test_latency_vs_db_fires_when_handler_dwarfs_db():
    handler = _span(
        op="inventory.handle_reserve",
        svc="inventory-service",
        span_id="h1",
        duration_us=305_000,
    )
    db = _span(
        op="db.decrement_stock",
        svc="inventory-service",
        span_id="d1",
        parent="h1",
        duration_us=1_200,
        attributes={"db.system": "postgresql"},
    )
    out = LatencyVsDBRule().evaluate(_ct([handler, db]))
    assert len(out) == 1
    h = out[0]
    assert h.severity == "medium"
    assert "database" in h.title.lower()


def test_latency_vs_db_silent_when_handler_fast():
    handler = _span(op="inventory.handle_reserve", span_id="h1", duration_us=10_000)
    db = _span(
        op="db.x",
        span_id="d1",
        parent="h1",
        duration_us=8_000,
        attributes={"db.system": "postgresql"},
    )
    assert LatencyVsDBRule().evaluate(_ct([handler, db])) == []


def test_latency_vs_db_silent_when_no_db_span():
    handler = _span(op="inventory.handle_reserve", span_id="h1", duration_us=305_000)
    assert LatencyVsDBRule().evaluate(_ct([handler])) == []


# --- determinism -------------------------------------------------------


@pytest.mark.parametrize(
    "rule_cls",
    [WebhookRaceRule, DownstreamErrorRule, LatencyVsDBRule],
)
def test_rules_are_deterministic(rule_cls):
    handler = _span(
        op="inventory.handle_reserve",
        svc="inventory-service",
        span_id="h1",
        duration_us=305_000,
    )
    db = _span(
        op="db.x",
        svc="inventory-service",
        span_id="d1",
        parent="h1",
        duration_us=1_200,
        attributes={"db.system": "postgresql"},
    )
    outer = _span(
        op="checkout.process",
        trace_id="t-co",
        span_id="co",
        start_ms=0,
        duration_us=300_000,
        attributes={"order.id": "ORD-1"},
        events=[
            _transition_event(0, "", "pending"),
            _transition_event(300, "pending", "confirmed"),
        ],
    )
    inner = _span(
        op="webhook.process",
        trace_id="t-wh",
        span_id="wh",
        start_ms=50,
        duration_us=1_000,
        attributes={"order.id": "ORD-1"},
        events=[_transition_event(50, "pending", "paid")],
    )
    parent = _span(op="HTTP POST", span_id="p1", status="ERROR")
    child = _span(op="x", svc="inventory-service", span_id="x", parent="p1", status="ERROR")
    ct = _ct([handler, db, outer, inner, parent, child])
    a = rule_cls().evaluate(ct)
    b = rule_cls().evaluate(ct)
    assert [h.title for h in a] == [h.title for h in b]
    assert [h.confidence for h in a] == [h.confidence for h in b]
