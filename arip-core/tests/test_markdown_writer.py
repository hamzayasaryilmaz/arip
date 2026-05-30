"""Smoke tests for the investigation-report markdown renderer.

This module's coverage was 0% before — the renderer is exercised
end-to-end by `bin/arip-demo.sh` but had no unit tests pinning the
output shape. These tests pin the **structure** of the markdown
without locking down every word, so prose changes don't churn the
test but structural regressions get caught.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arip_core.collector.failure_event import FailureEvent
from arip_core.engine.models import Evidence, Hypothesis
from arip_core.reporter.markdown_writer import (
    render,
    timeline_summary_from_items,
)
from arip_core.reporter.models import (
    FlakySignal,
    HistoryContext,
    InvestigationReport,
)

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _failure() -> FailureEvent:
    return FailureEvent(
        test_name="checkout fails under retry_storm",
        timestamp=NOW,
        environment="ci",
        trace_id="a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8",
        assertion="expect(response.status).toBe(200)",
        error_message="expected 200, got 503",
    )


def _hypothesis(rule: str = "retry_storm", conf: float = 0.93) -> Hypothesis:
    return Hypothesis(
        title=f"{rule}: 5 attempts to inventory.reserve",
        description="Five sequential attempts hit inventory-service ERROR.",
        confidence=conf,
        severity="high",
        rule_id=rule,
        evidence=[
            Evidence(
                kind="span",
                description="inventory.reserve_attempt 1/5",
                trace_id="a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8",
                span_id="s1",
                service="inventory-service",
                link="http://jaeger/trace/abc",
            ),
            Evidence(
                kind="log",
                description="inventory: upstream returned 503",
                trace_id="a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8",
                service="inventory-service",
            ),
        ],
        suggested_next_step="Inspect inventory-service for sustained 503s.",
    )


def _minimal_report(
    *,
    with_primary: bool = True,
    with_history: bool = False,
    with_flaky: bool = False,
    with_llm_summary: bool = False,
) -> InvestigationReport:
    return InvestigationReport(
        failure=_failure(),
        primary_hypothesis=_hypothesis() if with_primary else None,
        alternative_hypotheses=[],
        timeline_summary="payment-service → inventory-service ERROR",
        evidence_links=["http://jaeger/trace/abc"],
        generated_at=NOW,
        investigation_duration_seconds=8.7,
        primary_trace_id="a1b2c3d4e5f6a7b8a1b2c3d4e5f6a7b8",
        history=HistoryContext(
            fingerprint="fp123",
            occurrences_total=7,
            occurrences_window=3,
            window_days=14,
            first_seen=NOW,
            last_seen=NOW,
            affected_tests=["checkout fails under retry_storm"],
        )
        if with_history
        else None,
        flaky=FlakySignal(
            test_name="checkout fails under retry_storm",
            runs_considered=20,
            fail_rate=0.05,
            classification="stable",
            note="seen failing 1 of 20 runs",
        )
        if with_flaky
        else None,
        llm_summary="Most likely cause: retry storm against inventory-service."
        if with_llm_summary
        else None,
    )


# ---------- core rendering ----------------------------------------


def test_render_produces_non_empty_markdown_with_primary() -> None:
    md = render(_minimal_report())
    assert isinstance(md, str)
    assert len(md) > 100
    assert md.startswith("# ")


def test_render_includes_primary_hypothesis_block() -> None:
    md = render(_minimal_report())
    assert "Primary hypothesis" in md or "Primary Hypothesis" in md
    assert "retry_storm" in md
    # Confidence number rendered
    assert "0.93" in md
    # Suggested next step surfaced
    assert "inventory-service" in md


def test_render_cites_evidence_kinds() -> None:
    md = render(_minimal_report())
    # Both evidence kinds make it into the rendered report
    assert "span" in md.lower()
    assert "log" in md.lower()
    # Trace_id appears somewhere (citation or header)
    assert "a1b2c3d4e5f6a7b8" in md


def test_render_handles_no_primary_hypothesis() -> None:
    """Abstention case — render should still produce valid markdown."""
    md = render(_minimal_report(with_primary=False))
    assert isinstance(md, str)
    assert len(md) > 0
    assert md.startswith("# ")


def test_render_includes_history_when_present() -> None:
    md = render(_minimal_report(with_history=True))
    # Cross-run context section appears
    assert "7" in md  # occurrences_total
    assert "14" in md or "window" in md.lower()


def test_render_includes_flaky_signal_when_present() -> None:
    md = render(_minimal_report(with_flaky=True))
    assert "stable" in md.lower() or "flaky" in md.lower()


def test_render_includes_llm_summary_when_present() -> None:
    md = render(_minimal_report(with_llm_summary=True))
    assert "Most likely cause" in md


def test_render_includes_test_name_in_heading() -> None:
    md = render(_minimal_report())
    assert "checkout fails under retry_storm" in md


def test_render_includes_evidence_links() -> None:
    md = render(_minimal_report())
    assert "jaeger" in md


# ---------- timeline summary --------------------------------------


def test_timeline_summary_handles_empty_input() -> None:
    out = timeline_summary_from_items([])
    assert isinstance(out, str)


def test_timeline_summary_respects_limit() -> None:
    from arip_core.correlator.models import TimelineItem

    items = [
        TimelineItem(
            timestamp=NOW,
            kind="log",
            service="svc",
            summary=f"event {i}",
            detail={},
        )
        for i in range(100)
    ]
    out = timeline_summary_from_items(items, limit=10)
    # Output should be truncated, not contain all 100 events verbatim
    assert "event 99" not in out


# ---------- shape stability ---------------------------------------


def test_render_output_does_not_change_unexpectedly_across_calls() -> None:
    """Determinism: calling render() twice with identical input must
    produce byte-identical output. Catches accidental introduction of
    time.now() or random.* into the renderer."""
    report = _minimal_report(
        with_history=True,
        with_flaky=True,
        with_llm_summary=True,
    )
    a = render(report)
    b = render(report)
    assert a == b
