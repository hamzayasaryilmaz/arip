"""Translate Playwright's JSON reporter output into ``FailureEvent``s.

Playwright tests must attach two annotations when they exercise the
ARIP demo stack so we can correlate failures with telemetry:

    test.info().annotations.push({ type: 'trace_id',  description: traceId });
    test.info().annotations.push({ type: 'order_id',  description: orderId });
    test.info().annotations.push({ type: 'assertion', description: '...' });

The ``trace_id`` annotation is required for failure correlation;
everything else is best-effort.

This module exposes two parsers because the memory store needs both:
  * ``parse_report``     — only failures, mapped to FailureEvent
  * ``parse_test_runs``  — every test execution, used for flakiness
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .failure_event import FailureEvent


class PlaywrightReportError(Exception):
    """Raised when the Playwright JSON report cannot be parsed."""


@dataclass(frozen=True)
class TestRun:
    test_name: str
    status: str  # 'passed' | 'failed' | 'skipped' | 'flaky' | 'unknown'
    timestamp: datetime
    environment: str
    trace_id: str | None


def _walk_specs(suites: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield every spec across the (recursive) suite tree."""
    for suite in suites:
        for spec in suite.get("specs", []):
            yield spec
        yield from _walk_specs(suite.get("suites", []))


def _annotations(spec: dict[str, Any], test: dict[str, Any]) -> dict[str, str]:
    """Merge annotations from the spec and the individual test."""
    out: dict[str, str] = {}
    for source in (spec.get("annotations", []), test.get("annotations", [])):
        for ann in source:
            if "type" in ann and "description" in ann:
                out[ann["type"]] = ann["description"]
    return out


def parse_report(report_path: str | Path, environment: str = "demo") -> list[FailureEvent]:
    """Parse a ``playwright.json`` report and return one event per failure."""
    path = Path(report_path)
    if not path.exists():
        raise PlaywrightReportError(f"report not found: {path}")
    try:
        report = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PlaywrightReportError(f"invalid JSON: {exc}") from exc

    events: list[FailureEvent] = []
    for spec in _walk_specs(report.get("suites", [])):
        if spec.get("ok", True):
            continue
        for test in spec.get("tests", []):
            for result in test.get("results", []):
                if result.get("status") in {"passed", "skipped"}:
                    continue
                err = result.get("error") or {}
                anns = _annotations(spec, test)
                trace_id = anns.get("trace_id", "")
                if not trace_id:
                    # Skip silently — we cannot correlate without it.
                    continue
                ts = result.get("startTime")
                started = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if ts
                    else datetime.now(timezone.utc)
                )
                events.append(
                    FailureEvent(
                        test_name=spec.get("title", "<unknown>"),
                        timestamp=started,
                        environment=environment,
                        trace_id=trace_id,
                        assertion=anns.get("assertion", err.get("message", "").split("\n", 1)[0]),
                        error_message=err.get("message", ""),
                        stack_trace=err.get("stack"),
                        test_metadata={
                            "file": spec.get("file"),
                            "line": spec.get("line"),
                            "duration_ms": result.get("duration"),
                            "retry": result.get("retry", 0),
                            "annotations": anns,
                        },
                    )
                )
    return events


def parse_test_runs(report_path: str | Path, environment: str = "demo") -> list[TestRun]:
    """Return one TestRun per executed test (passed, failed, or skipped).

    Used to feed the cross-run memory store so flaky-test classification
    has data to work with.
    """
    path = Path(report_path)
    if not path.exists():
        raise PlaywrightReportError(f"report not found: {path}")
    report = json.loads(path.read_text())

    runs: list[TestRun] = []
    for spec in _walk_specs(report.get("suites", [])):
        title = spec.get("title", "<unknown>")
        for test in spec.get("tests", []):
            anns = _annotations(spec, test)
            trace_id = anns.get("trace_id")
            for result in test.get("results", []):
                status = result.get("status", "unknown")
                ts_raw = result.get("startTime")
                ts = (
                    datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if ts_raw
                    else datetime.now(timezone.utc)
                )
                runs.append(
                    TestRun(
                        test_name=title,
                        status=status,
                        timestamp=ts,
                        environment=environment,
                        trace_id=trace_id,
                    )
                )
    return runs
