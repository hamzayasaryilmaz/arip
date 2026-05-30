"""Tests for the Playwright JSON report listener.

The original test framework parser. Cypress is the second
(test_cypress_listener.py). This file closes the asymmetry — both
parsers now have unit coverage of the parse_report + parse_test_runs
+ detect_report_kind surfaces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arip_core.collector.cypress_listener import detect_report_kind
from arip_core.collector.playwright_listener import (
    PlaywrightReportError,
    parse_report,
    parse_test_runs,
)


def _make_report(specs: list[dict]) -> dict:
    return {
        "config": {"projects": [{"name": "chromium"}]},
        "suites": [{"title": "checkout.spec.ts", "specs": specs}],
    }


def _spec(
    *,
    title: str = "checkout flow",
    ok: bool = False,
    trace_id: str | None = "abcdef0123456789abcdef0123456789",
    test_results_status: str = "failed",
    err_message: str = "Timed out 5000ms",
) -> dict:
    annotations = []
    if trace_id:
        annotations.append({"type": "trace_id", "description": trace_id})
    return {
        "title": title,
        "ok": ok,
        "file": "tests/checkout.spec.ts",
        "line": 42,
        "annotations": annotations,
        "tests": [
            {
                "annotations": [],
                "results": [
                    {
                        "status": test_results_status,
                        "startTime": "2026-05-30T10:00:00.000Z",
                        "duration": 1234,
                        "retry": 0,
                        "error": {
                            "message": err_message,
                            "stack": f"Error: {err_message}\n  at line 42",
                        },
                    }
                ],
            }
        ],
    }


# ---------- parse_report ----------------------------------------------


def test_parse_report_extracts_failure_with_trace_id(tmp_path: Path) -> None:
    p = tmp_path / "pw.json"
    p.write_text(json.dumps(_make_report([_spec()])))
    events = parse_report(p)
    assert len(events) == 1
    ev = events[0]
    assert ev.trace_id == "abcdef0123456789abcdef0123456789"
    assert ev.environment == "demo"
    assert "Timed out" in ev.error_message
    assert ev.test_metadata["file"] == "tests/checkout.spec.ts"
    assert ev.test_metadata["line"] == 42


def test_parse_report_silently_skips_failures_without_trace_id(tmp_path: Path) -> None:
    p = tmp_path / "pw.json"
    p.write_text(json.dumps(_make_report([_spec(trace_id=None)])))
    assert parse_report(p) == []


def test_parse_report_ignores_passing_tests(tmp_path: Path) -> None:
    p = tmp_path / "pw.json"
    p.write_text(
        json.dumps(
            _make_report(
                [
                    _spec(ok=True, test_results_status="passed"),
                ]
            )
        )
    )
    assert parse_report(p) == []


def test_parse_report_handles_nested_suites(tmp_path: Path) -> None:
    """Playwright nests `suites` inside each suite for project/file
    grouping; the walker must recurse."""
    p = tmp_path / "pw.json"
    p.write_text(
        json.dumps(
            {
                "config": {},
                "suites": [
                    {
                        "title": "outer",
                        "suites": [
                            {
                                "title": "inner",
                                "specs": [_spec()],
                            }
                        ],
                    }
                ],
            }
        )
    )
    events = parse_report(p)
    assert len(events) == 1


def test_parse_report_merges_spec_and_test_annotations(tmp_path: Path) -> None:
    p = tmp_path / "pw.json"
    spec = _spec(trace_id="aaaa1111bbbb2222")
    # Move trace_id to test-level annotations rather than spec-level
    spec["annotations"] = []
    spec["tests"][0]["annotations"] = [{"type": "trace_id", "description": "aaaa1111bbbb2222"}]
    p.write_text(json.dumps(_make_report([spec])))
    events = parse_report(p)
    assert len(events) == 1
    assert events[0].trace_id == "aaaa1111bbbb2222"


def test_parse_report_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PlaywrightReportError, match="report not found"):
        parse_report(tmp_path / "missing.json")


def test_parse_report_raises_on_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(PlaywrightReportError, match="invalid JSON"):
        parse_report(bad)


# ---------- parse_test_runs -------------------------------------------


def test_parse_test_runs_returns_every_test(tmp_path: Path) -> None:
    p = tmp_path / "pw.json"
    p.write_text(
        json.dumps(
            _make_report(
                [
                    _spec(ok=True, test_results_status="passed", title="pass"),
                    _spec(test_results_status="failed", title="fail"),
                    _spec(test_results_status="skipped", title="skipped"),
                ]
            )
        )
    )
    runs = parse_test_runs(p)
    assert len(runs) == 3
    statuses = {r.status for r in runs}
    assert "passed" in statuses
    assert "failed" in statuses


# ---------- detect_report_kind interop --------------------------------


def test_playwright_report_is_detected_correctly(tmp_path: Path) -> None:
    """Cross-listener detection: a Playwright-shape JSON must be
    classified as 'playwright' by the detector, NOT misclassified as
    cypress. Regression for the CLI auto-detect codepath."""
    p = tmp_path / "pw.json"
    p.write_text(json.dumps(_make_report([_spec(ok=True, test_results_status="passed")])))
    assert detect_report_kind(p) == "playwright"
