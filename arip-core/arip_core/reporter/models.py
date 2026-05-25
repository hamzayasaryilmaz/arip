"""The final report shape — what gets written to disk and shown."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..collector.failure_event import FailureEvent
from ..engine.abstention import AbstentionReason
from ..engine.models import Hypothesis
from ..quality.assessment import QualityAssessment


@dataclass
class HistoryContext:
    """Cross-run context attached to a report by the memory layer."""

    fingerprint: str
    occurrences_total: int
    occurrences_window: int  # within recent N days
    window_days: int
    first_seen: datetime | None
    last_seen: datetime | None
    affected_tests: list[str] = field(default_factory=list)


@dataclass
class FlakySignal:
    test_name: str
    runs_considered: int
    fail_rate: float
    classification: str  # 'flaky' | 'genuine' | 'unknown'
    note: str


@dataclass
class InvestigationReport:
    failure: FailureEvent
    primary_hypothesis: Hypothesis | None
    alternative_hypotheses: list[Hypothesis]
    timeline_summary: str
    evidence_links: list[str]
    generated_at: datetime
    investigation_duration_seconds: float

    llm_summary: str | None = None
    primary_trace_id: str | None = None
    related_trace_ids: list[str] = field(default_factory=list)
    order_id: str | None = None

    # New fields driven by reliability/cross-run work.
    abstention: AbstentionReason | None = None
    history: HistoryContext | None = None
    flaky: FlakySignal | None = None
    telemetry_counts: dict[str, int] = field(default_factory=dict)

    # Diagnostic — purely informational. Set by the CLI after investigate().
    quality: QualityAssessment | None = None
