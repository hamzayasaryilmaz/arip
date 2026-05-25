"""Tests for the engine's abstention pathway.

The engine MUST decline to nominate a primary hypothesis when:
  * the primary trace is not in the telemetry backend
  * telemetry is entirely empty
  * no rule matched
  * the top hypothesis is too weak (low confidence or thin evidence)
"""

from __future__ import annotations

from datetime import datetime, timezone

from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry
from arip_core.engine.abstention import evaluate_abstention
from arip_core.engine.models import Evidence, Hypothesis

NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)


def _failure(trace_id: str = "tp") -> FailureEvent:
    return FailureEvent(
        test_name="t", timestamp=NOW, environment="test",
        trace_id=trace_id, assertion="x", error_message="boom",
    )


def _ct_with(spans=None, logs=None, primary_trace_id="tp") -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=_failure(trace_id=primary_trace_id),
        logs=logs or [],
        spans=spans or [],
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id=primary_trace_id,
    )


def _span(trace_id="tp"):
    from arip_core.correlator.models import Span
    return Span(
        trace_id=trace_id, span_id="s", parent_span_id=None,
        service_name="x", operation_name="op",
        start_time=NOW, duration_us=1, status="OK", status_message="",
        attributes={}, events=[],
    )


def _strong_hypothesis() -> Hypothesis:
    return Hypothesis(
        title="t", description="d", confidence=0.9, severity="high",
        rule_id="r",
        evidence=[
            Evidence(kind="span", description="x", trace_id="tp", span_id="s", service="x"),
            Evidence(kind="log", description="y", service="x"),
        ],
    )


def test_abstain_when_primary_trace_missing():
    ct = _ct_with(spans=[_span(trace_id="other")])  # no span carries primary_trace_id
    a = evaluate_abstention(ct, [_strong_hypothesis()])
    assert a is not None
    assert a.code == "no_primary_trace"


def test_abstain_on_empty_telemetry():
    # Both empty AND no primary trace match → no_primary_trace wins
    # (it is the more specific reason).
    ct = _ct_with(spans=[], logs=[])
    a = evaluate_abstention(ct, [])
    assert a is not None
    assert a.code == "no_primary_trace"


def test_abstain_when_no_rule_matched():
    ct = _ct_with(spans=[_span()])
    a = evaluate_abstention(ct, [])
    assert a is not None
    assert a.code == "no_rule_matched"


def test_abstain_on_weak_confidence():
    h = _strong_hypothesis()
    h.confidence = 0.5
    ct = _ct_with(spans=[_span()])
    a = evaluate_abstention(ct, [h])
    assert a is not None
    assert a.code == "weak_evidence"


def test_abstain_on_single_evidence_kind():
    h = _strong_hypothesis()
    h.evidence = [Evidence(kind="span", description="x", trace_id="tp", span_id="s")]  # only one kind
    ct = _ct_with(spans=[_span()])
    a = evaluate_abstention(ct, [h])
    assert a is not None
    assert a.code == "weak_evidence"


def test_does_not_abstain_when_hypothesis_well_grounded():
    ct = _ct_with(spans=[_span()])
    a = evaluate_abstention(ct, [_strong_hypothesis()])
    assert a is None


# --- conflicting_hypotheses --------------------------------------------


def _h_with_evidence(rule_id, conf, evidence_kinds_and_ids):
    """Build a hypothesis with controlled evidence."""
    evs = [
        Evidence(kind=k, description=d, trace_id="tp", span_id=sid, service="x")
        for k, sid, d in evidence_kinds_and_ids
    ]
    return Hypothesis(
        title=f"{rule_id} title",
        description="d",
        confidence=conf,
        severity="high",
        rule_id=rule_id,
        evidence=evs,
    )


def test_abstain_on_conflicting_hypotheses_disjoint_evidence():
    # Two hypotheses with similar BUT non-dominant confidence and
    # completely different evidence. Both are in the "ambiguous" zone
    # below CONFLICT_TOP_CONFIDENCE_CEILING — the engine cannot trust
    # either one outright, so it should abstain.
    a = _h_with_evidence("downstream_error", 0.78, [
        ("span", "s-http-post", "HTTP POST ERROR"),
        ("log",  None,          "inventory: reserve failed"),
    ])
    b = _h_with_evidence("latency_vs_db", 0.76, [
        ("span", "s-handle",     "handler 250ms"),
        ("span", "s-db-update",  "db.decrement_stock 3ms"),
        ("log",  None,           "different log entirely"),
    ])
    ct = _ct_with(spans=[_span()])
    result = evaluate_abstention(ct, [a, b])
    assert result is not None
    assert result.code == "conflicting_hypotheses"
    assert "downstream_error" in result.detail
    assert "latency_vs_db" in result.detail


def test_no_conflict_when_overlapping_evidence():
    # Same rule_id family on overlapping evidence — agreement, not conflict.
    a = _h_with_evidence("downstream_error", 0.90, [
        ("span", "s-shared",  "shared evidence"),
        ("log",  None,        "shared log line"),
    ])
    b = _h_with_evidence("retry_storm", 0.85, [
        ("span", "s-shared",  "shared evidence"),
        ("log",  None,        "shared log line"),
    ])
    ct = _ct_with(spans=[_span()])
    result = evaluate_abstention(ct, [a, b])
    # Should NOT trigger conflict_hypotheses (high overlap)
    assert result is None or result.code != "conflicting_hypotheses"


def test_no_conflict_when_confidence_delta_too_large():
    # Top is much more confident; clearly the primary, no conflict.
    a = _h_with_evidence("downstream_error", 0.92, [
        ("span", "s-a", "a"),
        ("log",  None,  "a"),
    ])
    b = _h_with_evidence("latency_vs_db", 0.75, [
        ("span", "s-b", "b"),
        ("log",  None,  "b"),
    ])
    ct = _ct_with(spans=[_span()])
    result = evaluate_abstention(ct, [a, b])
    assert result is None or result.code != "conflicting_hypotheses"


def test_no_conflict_when_top_hypothesis_is_highly_confident():
    """If the top hypothesis is already above the ceiling, the engine
    should trust it rather than abstain. Otherwise every clean primary
    finding would be drowned out by a weaker second-place hypothesis."""
    # Top is comfortably above the ceiling; second is below it.
    a = _h_with_evidence("downstream_error", 0.93, [
        ("span", "s-a", "a-span"),
        ("log",  None,  "a-log"),
    ])
    b = _h_with_evidence("latency_vs_db", 0.86, [
        ("span", "s-b", "b-span"),
        ("log",  None,  "b-log"),
    ])
    ct = _ct_with(spans=[_span()])
    result = evaluate_abstention(ct, [a, b])
    # Even though evidence is disjoint and delta is small, a is strong
    # enough on its own that we trust it.
    assert result is None or result.code != "conflicting_hypotheses"


def test_no_conflict_when_one_side_has_thin_evidence():
    # b has only one evidence kind — not strong enough to "conflict".
    a = _h_with_evidence("downstream_error", 0.87, [
        ("span", "s-a", "a"),
        ("log",  None,  "a"),
    ])
    b = _h_with_evidence("latency_vs_db", 0.86, [
        ("span", "s-b", "b"),
    ])
    ct = _ct_with(spans=[_span()])
    result = evaluate_abstention(ct, [a, b])
    assert result is None or result.code != "conflicting_hypotheses"
