"""Translate Cypress's JSON reporter output into ``FailureEvent``s.

Cypress emits a JSON report when run with `mocha-json-reporter`
or with the built-in `--reporter json`. The shape:

    {
      "stats": {...},
      "results": [
        {
          "file": "cypress/e2e/checkout.cy.ts",
          "suites": [{"title": "...", "tests": [...]}],
          "tests": [...]  // may be top-level too
        }
      ]
    }

Each test has:
  - `title`: human test name
  - `state`: 'passed' | 'failed' | 'pending'
  - `pass` / `fail` / `pending`: boolean
  - `err`: { message, estack, stack } when failed
  - `duration`: ms
  - `currentRetry` / `retries`: integers

Cypress doesn't have Playwright's annotations API. Operators
correlate failures with telemetry by injecting trace_id into
either:
  1. The test title (e.g. "checkout [trace_id=abc...]")
  2. A custom `extra` object attached via mocharc or test context
  3. The failure message (if assertion includes the trace_id)

This parser checks all three in that order. If no trace_id is
recoverable, the failure is dropped (same discipline as the
Playwright listener).

Exposed parsers:
  * ``parse_report``    — only failures, mapped to FailureEvent
  * ``parse_test_runs`` — every test execution, for flakiness
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .failure_event import FailureEvent


class CypressReportError(Exception):
    """Raised when the Cypress JSON report cannot be parsed."""


@dataclass(frozen=True)
class TestRun:
    test_name: str
    status: str  # 'passed' | 'failed' | 'pending' | 'unknown'
    timestamp: datetime
    environment: str
    trace_id: str | None


# Patterns to extract trace_id from various places Cypress operators
# typically embed it. Hex 16 or 32 chars (the standard OTel trace ID
# lengths), optionally tagged with `trace_id=` or `traceId=`.
_TRACE_ID_PATTERNS = [
    # Accepts JSON-quoted ("trace_id": "abc") or shell-style (trace_id=abc).
    re.compile(r'trace[_-]?id["\']?\s*[=:]\s*["\']?([a-fA-F0-9]{16,32})'),
    re.compile(r'traceId["\']?\s*[=:]\s*["\']?([a-fA-F0-9]{16,32})'),
    re.compile(r"\btraceparent[=:]\s*\d+-([a-fA-F0-9]{32})-"),
]


def _extract_trace_id(*sources: str | None) -> str | None:
    """Search the given strings for an embedded trace_id."""
    for src in sources:
        if not src:
            continue
        for pat in _TRACE_ID_PATTERNS:
            m = pat.search(src)
            if m:
                return m.group(1)
    return None


def _walk_tests(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every test in a (possibly-nested) Cypress result node."""
    yield from node.get("tests", []) or []
    for suite in node.get("suites", []) or []:
        yield from _walk_tests(suite)


def _walk_all_tests(report: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every test across all top-level results."""
    for result in report.get("results", []) or []:
        yield from _walk_tests(result)
    # Some Cypress versions put tests at the top level directly.
    yield from _walk_tests(report)


def _classify_status(test: dict[str, Any]) -> str:
    if test.get("pass") is True or test.get("state") == "passed":
        return "passed"
    if test.get("fail") is True or test.get("state") == "failed":
        return "failed"
    if test.get("pending") is True or test.get("state") == "pending":
        return "pending"
    return "unknown"


def _parse_timestamp(report: dict[str, Any], test: dict[str, Any]) -> datetime:
    """Cypress doesn't always emit per-test start times. Fall back to
    the report's `stats.start` (whole-run start) — operator can
    correlate via trace_id timestamp instead."""
    ts = test.get("startTime") or test.get("start")
    if ts:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            pass
    stats = report.get("stats") or {}
    run_start = stats.get("start")
    if run_start:
        try:
            return datetime.fromisoformat(str(run_start).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def parse_report(report_path: str | Path, environment: str = "cypress") -> list[FailureEvent]:
    """Parse a Cypress JSON report → one event per failure."""
    path = Path(report_path)
    if not path.exists():
        raise CypressReportError(f"report not found: {path}")
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CypressReportError(f"invalid JSON: {exc}") from exc

    events: list[FailureEvent] = []
    for test in _walk_all_tests(report):
        if _classify_status(test) != "failed":
            continue
        err = test.get("err") or {}
        # Cypress sometimes uses 'extra' or 'context' for operator annotations.
        extras = test.get("extra") or test.get("context") or {}
        # trace_id can live in any of: test title, err.message, err.stack,
        # extras dict (any value), file path
        trace_id = _extract_trace_id(
            test.get("title"),
            test.get("fullTitle"),
            test.get("file"),
            err.get("message"),
            err.get("estack") or err.get("stack"),
            json.dumps(extras) if extras else None,
        )
        if not trace_id:
            # Silent skip — cannot correlate without trace_id.
            # Same discipline as Playwright listener.
            continue
        started = _parse_timestamp(report, test)
        events.append(
            FailureEvent(
                test_name=test.get("title", "<unknown>"),
                timestamp=started,
                environment=environment,
                trace_id=trace_id,
                assertion=err.get("message", "").split("\n", 1)[0],
                error_message=err.get("message", ""),
                stack_trace=err.get("estack") or err.get("stack"),
                test_metadata={
                    "file": test.get("file"),
                    "duration_ms": test.get("duration"),
                    "retry": test.get("currentRetry", 0),
                    "fullTitle": test.get("fullTitle"),
                    "extras": extras if extras else None,
                },
            )
        )
    return events


def parse_test_runs(report_path: str | Path, environment: str = "cypress") -> list[TestRun]:
    """Return one TestRun per executed test (passed, failed, or pending).

    Used to feed cross-run memory for flakiness classification.
    """
    path = Path(report_path)
    if not path.exists():
        raise CypressReportError(f"report not found: {path}")
    report = json.loads(path.read_text())

    runs: list[TestRun] = []
    for test in _walk_all_tests(report):
        err = test.get("err") or {}
        extras = test.get("extra") or test.get("context") or {}
        trace_id = _extract_trace_id(
            test.get("title"),
            test.get("fullTitle"),
            test.get("file"),
            err.get("message"),
            err.get("estack") or err.get("stack"),
            json.dumps(extras) if extras else None,
        )
        runs.append(
            TestRun(
                test_name=test.get("title", "<unknown>"),
                status=_classify_status(test),
                timestamp=_parse_timestamp(report, test),
                environment=environment,
                trace_id=trace_id,
            )
        )
    return runs


def detect_report_kind(report_path: str | Path) -> str:
    """Return 'playwright' | 'cypress' | 'unknown' for a JSON report.

    Heuristic — Cypress reports have a `stats` object and either
    `results` (mochawesome / mocha-json-reporter shape) or
    `runs` (Cypress >= 10 native reporter shape, no JSON output by
    default but used by some CI plugins). Playwright reports have a
    top-level `suites` key. If both look possible, return 'unknown'
    and let the operator pick.
    """
    try:
        data = json.loads(Path(report_path).read_text())
    except (json.JSONDecodeError, OSError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    if "suites" in data and "stats" not in data:
        return "playwright"
    if "stats" in data and ("results" in data or "passes" in data or "tests" in data):
        return "cypress"
    return "unknown"
