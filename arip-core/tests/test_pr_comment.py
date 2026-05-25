"""Tests for the GitHub PR comment renderer."""

from __future__ import annotations

from arip_core.integrations.github import HEADER, render_pr_comment


def _report(
    *,
    test_name="t",
    primary=None,
    abstention=None,
    flaky=None,
    history=None,
) -> dict:
    return {
        "failure": {"test_name": test_name, "trace_id": "tp"},
        "primary_hypothesis": primary,
        "alternative_hypotheses": [],
        "abstention": abstention,
        "flaky": flaky,
        "history": history,
        "evidence_links": [],
    }


def test_empty_input_returns_clean_message():
    out = render_pr_comment([])
    assert HEADER in out
    assert "No failures" in out


def test_includes_failure_count_in_header():
    out = render_pr_comment([_report(), _report()])
    assert "**2** failure(s)" in out


def test_renders_primary_hypothesis():
    out = render_pr_comment([
        _report(primary={
            "title": "Concurrent modification",
            "description": "Two traces overlapped.",
            "severity": "high",
            "confidence": 0.92,
            "rule_id": "concurrent_modification",
            "suggested_next_step": "Gate the transition.",
            "evidence": [{"kind": "span", "description": "spanA"}],
        })
    ])
    assert "Concurrent modification" in out
    assert "concurrent_modification" in out
    assert "Gate the transition" in out


def test_renders_abstention():
    out = render_pr_comment([
        _report(abstention={
            "code": "no_primary_trace",
            "headline": "Primary trace not found.",
            "detail": "The trace_id never appeared in Jaeger.",
        })
    ])
    assert "abstained" in out.lower()
    assert "Primary trace not found." in out


def test_surfaces_flaky_badge():
    out = render_pr_comment([
        _report(flaky={
            "classification": "flaky",
            "fail_rate": 0.4,
            "runs_considered": 10,
        })
    ])
    assert "Flaky test" in out
    assert "40%" in out


def test_surfaces_cross_run_repeats():
    out = render_pr_comment([
        _report(history={
            "occurrences_total": 5,
            "occurrences_window": 3,
            "window_days": 14,
            "fingerprint": "abc123",
        })
    ])
    assert "Seen **5** time(s)" in out


def test_respects_max_bytes_budget():
    primary = {
        "title": "X" * 50,
        "description": "Y" * 2000,
        "severity": "high",
        "confidence": 0.9,
        "rule_id": "r",
        "evidence": [],
    }
    reports = [_report(primary=primary) for _ in range(200)]
    out = render_pr_comment(reports, max_bytes=10_000)
    assert len(out) <= 12_000  # budget plus a bit of overhead for truncation note
    assert "omitted" in out
