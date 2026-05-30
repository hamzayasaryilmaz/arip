"""Tests for the Cypress JSON report listener.

Cypress is the second test framework ARIP supports for investigation
mode (after Playwright). Operators correlate failures with telemetry
by injecting trace_id into test titles, error messages, or extras
because Cypress lacks Playwright's structured annotations API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arip_core.collector.cypress_listener import (
    CypressReportError,
    detect_report_kind,
    parse_report,
    parse_test_runs,
)


def _make_cypress_report(tests: list[dict]) -> dict:
    """Build a realistic Cypress mochawesome-shape report."""
    return {
        "stats": {
            "suites": 1,
            "tests": len(tests),
            "passes": sum(1 for t in tests if t.get("pass")),
            "pending": 0,
            "failures": sum(1 for t in tests if t.get("fail")),
            "start": "2026-05-30T10:00:00.000Z",
            "end": "2026-05-30T10:00:42.123Z",
            "duration": 42123,
        },
        "results": [
            {
                "uuid": "abc",
                "file": "cypress/e2e/checkout.cy.ts",
                "fullFile": "/abs/path/cypress/e2e/checkout.cy.ts",
                "suites": [
                    {
                        "title": "checkout flow",
                        "tests": tests,
                    }
                ],
                "tests": [],
            }
        ],
    }


def _passing_test(title: str = "checkout succeeds", trace_id_in_title: bool = False) -> dict:
    t = {
        "title": f"{title} [trace_id={'a' * 32}]" if trace_id_in_title else title,
        "fullTitle": f"checkout flow > {title}",
        "duration": 1234,
        "state": "passed",
        "pass": True,
        "fail": False,
        "pending": False,
        "err": {},
    }
    return t


def _failing_test(
    *,
    title: str = "checkout fails",
    trace_id: str | None = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    trace_id_location: str = "title",
    err_message: str = "Timed out retrying after 4000ms",
) -> dict:
    if trace_id_location == "title" and trace_id:
        full_title = f"{title} [trace_id={trace_id}]"
    else:
        full_title = title
    msg = err_message
    if trace_id_location == "err_message" and trace_id:
        msg = f"{err_message} (trace_id={trace_id})"
    extras = {}
    if trace_id_location == "extras" and trace_id:
        extras = {"trace_id": trace_id, "order_id": "ORD-1"}
    return {
        "title": full_title,
        "fullTitle": f"checkout flow > {full_title}",
        "duration": 4321,
        "state": "failed",
        "pass": False,
        "fail": True,
        "pending": False,
        "err": {
            "message": msg,
            "estack": f"AssertionError: {msg}\n  at /cypress/e2e/checkout.cy.ts:42:7",
            "stack": f"AssertionError: {msg}",
        },
        "file": "cypress/e2e/checkout.cy.ts",
        "currentRetry": 0,
        "extra": extras if extras else None,
    }


# ---------- parse_report ----------------------------------------------


def test_parse_report_extracts_failure_with_trace_id_in_title(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _failing_test(trace_id_location="title"),
                ]
            )
        )
    )

    events = parse_report(report_path)
    assert len(events) == 1
    ev = events[0]
    assert ev.trace_id == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert ev.environment == "cypress"
    assert "Timed out" in ev.error_message
    assert ev.test_metadata["file"] == "cypress/e2e/checkout.cy.ts"


def test_parse_report_extracts_trace_id_from_err_message(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _failing_test(trace_id_location="err_message"),
                ]
            )
        )
    )
    events = parse_report(report_path)
    assert len(events) == 1
    assert events[0].trace_id == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"


def test_parse_report_extracts_trace_id_from_extras(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _failing_test(trace_id_location="extras"),
                ]
            )
        )
    )
    events = parse_report(report_path)
    assert len(events) == 1
    assert events[0].trace_id == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"


def test_parse_report_supports_traceparent_format(tmp_path: Path) -> None:
    """W3C traceparent format like `00-<trace_id>-<span_id>-01`."""
    tp = "00-1111111122222222333333334444444a-aaaabbbbccccdddd-01"
    test = _failing_test(trace_id=None)
    test["title"] = f"checkout fails (traceparent={tp})"
    test["err"]["message"] = "boom"
    report_path = tmp_path / "cypress.json"
    report_path.write_text(json.dumps(_make_cypress_report([test])))
    events = parse_report(report_path)
    assert len(events) == 1
    assert events[0].trace_id == "1111111122222222333333334444444a"


def test_parse_report_silently_skips_failures_without_trace_id(tmp_path: Path) -> None:
    """No trace_id anywhere → can't correlate → drop."""
    test = _failing_test(trace_id=None)
    test["title"] = "checkout fails"  # no trace_id
    test["err"]["message"] = "no trace info"
    test["err"]["estack"] = "stack with no ids"
    report_path = tmp_path / "cypress.json"
    report_path.write_text(json.dumps(_make_cypress_report([test])))
    assert parse_report(report_path) == []


def test_parse_report_ignores_passing_tests(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _passing_test(),
                    _passing_test(title="another passes"),
                ]
            )
        )
    )
    assert parse_report(report_path) == []


def test_parse_report_handles_nested_suites(tmp_path: Path) -> None:
    """Cypress allows nested suite trees; parser must walk them."""
    failing = _failing_test()
    nested = {
        "stats": {
            "suites": 2,
            "tests": 1,
            "passes": 0,
            "pending": 0,
            "failures": 1,
            "start": "2026-05-30T10:00:00.000Z",
            "end": "2026-05-30T10:00:01.000Z",
            "duration": 1000,
        },
        "results": [
            {
                "file": "x.cy.ts",
                "suites": [
                    {
                        "title": "outer",
                        "suites": [
                            {
                                "title": "inner",
                                "tests": [failing],
                            }
                        ],
                        "tests": [],
                    }
                ],
                "tests": [],
            }
        ],
    }
    report_path = tmp_path / "cypress.json"
    report_path.write_text(json.dumps(nested))
    events = parse_report(report_path)
    assert len(events) == 1


def test_parse_report_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CypressReportError, match="report not found"):
        parse_report(tmp_path / "does-not-exist.json")


def test_parse_report_raises_on_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    with pytest.raises(CypressReportError, match="invalid JSON"):
        parse_report(bad)


# ---------- parse_test_runs -------------------------------------------


def test_parse_test_runs_returns_every_test_including_passes(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _passing_test(),
                    _failing_test(),
                    {
                        "title": "skipped one",
                        "pending": True,
                        "state": "pending",
                        "pass": False,
                        "fail": False,
                        "err": {},
                    },
                ]
            )
        )
    )
    runs = parse_test_runs(report_path)
    assert len(runs) == 3
    statuses = [r.status for r in runs]
    assert "passed" in statuses
    assert "failed" in statuses
    assert "pending" in statuses


def test_parse_test_runs_preserves_trace_id_when_available(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(
        json.dumps(
            _make_cypress_report(
                [
                    _failing_test(),
                    _passing_test(),
                ]
            )
        )
    )
    runs = parse_test_runs(report_path)
    failed = [r for r in runs if r.status == "failed"]
    assert len(failed) == 1
    assert failed[0].trace_id is not None


# ---------- detect_report_kind ----------------------------------------


def test_detect_report_kind_cypress(tmp_path: Path) -> None:
    report_path = tmp_path / "cypress.json"
    report_path.write_text(json.dumps(_make_cypress_report([_passing_test()])))
    assert detect_report_kind(report_path) == "cypress"


def test_detect_report_kind_playwright(tmp_path: Path) -> None:
    """Playwright reports have `suites` at the top level, no `stats`."""
    report_path = tmp_path / "pw.json"
    report_path.write_text(
        json.dumps(
            {
                "config": {},
                "suites": [{"title": "x", "specs": []}],
            }
        )
    )
    assert detect_report_kind(report_path) == "playwright"


def test_detect_report_kind_unknown(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"foo": "bar"}))
    assert detect_report_kind(bad) == "unknown"


def test_detect_report_kind_missing_file(tmp_path: Path) -> None:
    assert detect_report_kind(tmp_path / "missing.json") == "unknown"


def test_detect_report_kind_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert detect_report_kind(bad) == "unknown"
