"""Tests for assertion classifier + alignment-based confidence boost."""

from __future__ import annotations

from arip_core.engine.assertion import (
    RULE_ALIGNMENT,
    adjust_for_assertion,
    classify_assertion,
)
from arip_core.engine.models import Evidence, Hypothesis


def _h(rule_id: str, conf: float = 0.85) -> Hypothesis:
    return Hypothesis(
        title="t", description="d", confidence=conf, severity="high",
        rule_id=rule_id,
        evidence=[Evidence(kind="span", description="x", span_id="s", trace_id="t")],
    )


# --- classify_assertion ----------------------------------------------


def test_classify_latency_assertion():
    assert classify_assertion("checkout completes within 150ms") == {"latency"}
    assert classify_assertion("response under SLA") == {"latency"}
    assert classify_assertion("each request completes in <500ms") == {"latency"}


def test_classify_status_assertion():
    assert "status" in classify_assertion("checkout returns 200 OK")
    assert "status" in classify_assertion("response status is 200")


def test_classify_correctness_assertion():
    assert "correctness" in classify_assertion("order history has no interleaved trace_ids")
    assert "correctness" in classify_assertion("state transitions are consistent")


def test_classify_empty_assertion():
    assert classify_assertion("") == set()
    assert classify_assertion("   ") == set()


def test_classify_can_produce_multiple_tags():
    tags = classify_assertion("response within 200ms with status 200")
    assert "latency" in tags
    assert "status" in tags


# --- adjust_for_assertion --------------------------------------------


def test_aligned_rule_gets_confidence_boost():
    hypotheses = [_h("latency_vs_db", conf=0.85)]
    out = adjust_for_assertion(hypotheses, "checkout completes within 150ms")
    assert out[0].confidence == 0.88


def test_misaligned_rule_gets_confidence_decay():
    # latency_vs_db on a status assertion → misaligned
    hypotheses = [_h("latency_vs_db", conf=0.85)]
    out = adjust_for_assertion(hypotheses, "checkout returns 200 OK")
    assert out[0].confidence == 0.82


def test_unknown_rule_unchanged():
    hypotheses = [_h("mystery_rule", conf=0.85)]
    out = adjust_for_assertion(hypotheses, "checkout returns 200")
    assert out[0].confidence == 0.85


def test_empty_assertion_passes_through():
    hypotheses = [_h("latency_vs_db", conf=0.85)]
    out = adjust_for_assertion(hypotheses, "")
    assert out[0].confidence == 0.85


def test_clamp_to_max_confidence():
    hypotheses = [_h("latency_vs_db", conf=0.94)]
    out = adjust_for_assertion(hypotheses, "checkout completes within 150ms")
    assert out[0].confidence <= 0.95


def test_clamp_to_min_confidence():
    hypotheses = [_h("latency_vs_db", conf=0.01)]
    out = adjust_for_assertion(hypotheses, "checkout returns 200 OK")
    assert out[0].confidence >= 0.0


def test_alignment_is_set_complete():
    """The rule alignment table must cover every shipped rule_id."""
    from arip_core.engine.hypothesis import default_rules
    shipped = {r.rule_id for r in default_rules()}
    documented = set(RULE_ALIGNMENT.keys())
    missing = shipped - documented
    assert not missing, f"rules without RULE_ALIGNMENT entry: {missing}"
