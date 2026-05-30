"""Tests for the memory store: fingerprinting, history, flaky verdict."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arip_core.collector.failure_event import FailureEvent
from arip_core.engine.models import Evidence, Hypothesis
from arip_core.memory.fingerprint import fingerprint_hypothesis
from arip_core.memory.flaky import FlakyClassifier
from arip_core.memory.store import MemoryStore
from arip_core.reporter.models import InvestigationReport

NOW = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.db")


def _h(rule_id: str, services: list[str], kinds: list[str]) -> Hypothesis:
    evidence = [
        Evidence(
            kind=k, description="d", trace_id="tp", span_id="s", service=services[i % len(services)]
        )
        for i, k in enumerate(kinds)
    ]
    return Hypothesis(
        title="t",
        description="d",
        confidence=0.9,
        severity="high",
        rule_id=rule_id,
        evidence=evidence,
    )


def _report(
    test_name: str, trace_id: str, primary: Hypothesis | None = None
) -> InvestigationReport:
    return InvestigationReport(
        failure=FailureEvent(
            test_name=test_name,
            timestamp=NOW,
            environment="ci",
            trace_id=trace_id,
            assertion="x",
            error_message="e",
        ),
        primary_hypothesis=primary,
        alternative_hypotheses=[],
        timeline_summary="",
        evidence_links=[],
        generated_at=NOW,
        investigation_duration_seconds=0.0,
        primary_trace_id=trace_id,
    )


# --- fingerprint ----------------------------------------------------


def test_fingerprint_is_stable():
    h = _h(
        "concurrent_modification",
        ["payment-service", "payment-service"],
        ["span", "span_event", "log"],
    )
    assert fingerprint_hypothesis(h) == fingerprint_hypothesis(h)


def test_fingerprint_independent_of_trace_id():
    a = _h("r1", ["s1"], ["span"])
    a.evidence[0].trace_id = "trace-A"
    b = _h("r1", ["s1"], ["span"])
    b.evidence[0].trace_id = "trace-B"
    assert fingerprint_hypothesis(a) == fingerprint_hypothesis(b)


def test_fingerprint_changes_with_rule_id():
    a = _h("r1", ["s1"], ["span"])
    b = _h("r2", ["s1"], ["span"])
    assert fingerprint_hypothesis(a) != fingerprint_hypothesis(b)


def test_fingerprint_changes_with_service_set():
    a = _h("r1", ["s1"], ["span"])
    b = _h("r1", ["s2"], ["span"])
    assert fingerprint_hypothesis(a) != fingerprint_hypothesis(b)


# --- store + history -----------------------------------------------


def test_history_records_and_returns_occurrences(store: MemoryStore):
    h = _h("concurrent_modification", ["payment-service"], ["span", "span_event"])
    fp = fingerprint_hypothesis(h)

    for i in range(3):
        rep = _report(f"test-{i}", f"trace-{i}", primary=h)
        store.record_investigation(rep, fingerprint=fp, report_path=f"/x/{i}.md")

    hist = store.history_for_fingerprint(fp, window_days=30)
    assert hist.occurrences_total == 3
    assert hist.occurrences_window == 3
    assert len(hist.affected_tests) == 3


def test_history_empty_for_unseen_fingerprint(store: MemoryStore):
    hist = store.history_for_fingerprint("unseen-fp")
    assert hist.occurrences_total == 0
    assert hist.first_seen is None


def test_test_run_stats_counts_fails(store: MemoryStore):
    store.record_test_runs_bulk(
        [
            ("checkout", "passed", NOW, "ci", None),
            ("checkout", "failed", NOW - timedelta(minutes=1), "ci", None),
            ("checkout", "passed", NOW - timedelta(minutes=2), "ci", None),
            ("other", "failed", NOW, "ci", None),
        ]
    )
    considered, fails = store.test_run_stats("checkout", last_n=10)
    assert considered == 3
    assert fails == 1


# --- flaky --------------------------------------------------------


def test_flaky_classifier_unknown_until_min_runs():
    v = FlakyClassifier().classify(runs_considered=2, fails=1)
    assert v.classification == "unknown"


def test_flaky_classifier_flags_mid_rates():
    v = FlakyClassifier().classify(runs_considered=10, fails=3)
    assert v.classification == "flaky"
    assert v.fail_rate == 0.3


def test_flaky_classifier_calls_consistently_failing_genuine():
    v = FlakyClassifier().classify(runs_considered=10, fails=10)
    assert v.classification == "genuine"


def test_flaky_classifier_calls_consistently_passing_genuine():
    v = FlakyClassifier().classify(runs_considered=10, fails=0)
    assert v.classification == "genuine"
