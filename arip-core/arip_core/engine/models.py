"""Dataclasses for hypotheses and the evidence backing them.

A core property: **every hypothesis must cite at least one Evidence
record**, and every Evidence record must point at something a human can
open and verify. No free-floating claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


@dataclass
class Evidence:
    """A pointer at a single artefact: a span, an event, a log line,
    or a piece of state-history. The ``link`` field is a URL when the
    backend supports one (Jaeger), otherwise empty."""

    kind: str  # 'span' | 'span_event' | 'log' | 'db_query'
    description: str
    trace_id: str | None = None
    span_id: str | None = None
    service: str | None = None
    link: str | None = None
    snippet: str | None = None


@dataclass
class Hypothesis:
    title: str
    description: str
    confidence: float  # 0.0 - 1.0
    severity: str  # 'low' | 'medium' | 'high'
    evidence: list[Evidence] = field(default_factory=list)
    suggested_next_step: str | None = None
    rule_id: str | None = None
    # Per-hypothesis evidence-kinds floor (field-test F6).
    # Default 2 matches the engine-wide trust contract: every primary
    # must be backed by at least two distinct evidence KINDS (e.g.
    # span + log). Rules that fundamentally produce a single-kind
    # signal at high confidence (e.g. latency_vs_db, where the
    # disproportion IS the evidence and correlated error logs don't
    # exist in many cases) may lower this to 1 when they're already
    # demanding a sharp threshold. Raising the bar for the abstention
    # layer beyond 2 is allowed but rarely needed.
    min_evidence_kinds: int = 2

    @property
    def rank(self) -> tuple[int, float]:
        return (SEVERITY_RANK.get(self.severity, 0), self.confidence)
