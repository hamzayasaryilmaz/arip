"""Abstention: the engine's "I don't know" pathway.

A trustworthy investigator must be able to say "telemetry insufficient"
or "no known pattern matched" instead of always producing a hypothesis.
Reports that abstain are surfaced as such and are NOT counted as
investigations for ranking/fingerprinting purposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..correlator.models import CorrelatedTelemetry
from .models import Hypothesis

# A hypothesis below this confidence is treated as too weak to be primary.
WEAK_CONFIDENCE_CEILING = 0.7

# A primary hypothesis must have at least this many distinct evidence kinds
# (e.g. {'span', 'log', 'span_event'}) to be considered well-grounded.
MIN_EVIDENCE_KINDS = 2

# Conflict detection thresholds. Two hypotheses are "conflicting" when:
#   - the top hypothesis is below CONFLICT_TOP_CONFIDENCE_CEILING — if it
#     were higher, the engine's own ranking is already strong enough that
#     we should trust it rather than abstain;
#   - both confidences ≥ CONFLICT_MIN_CONFIDENCE — they are both serious
#     candidates;
#   - their confidence delta < CONFLICT_DELTA — neither has cleanly won;
#   - their cited evidence (span_id ∪ log message) overlaps less than
#     CONFLICT_MAX_OVERLAP — they are pointing at different parts of
#     the trace.
CONFLICT_DELTA = 0.10
CONFLICT_MIN_CONFIDENCE = 0.7
CONFLICT_TOP_CONFIDENCE_CEILING = 0.85
CONFLICT_MAX_OVERLAP = 0.30


_NEXT_STEPS: dict[str, str] = {
    "no_primary_trace": (
        "Bump the OTel SDK flush sleep before ARIP investigates (the trace may "
        "not have flushed yet). If it persists across runs, your sampling "
        "config is dropping the trace before Jaeger sees it — check tail-based "
        "sampling rules in the OTel Collector. See docs/ONBOARDING.md."
    ),
    "empty_telemetry": (
        "Verify your telemetry pipeline is flowing during the failure window: "
        "service emitting OTel? Collector receiving? Backend (Jaeger/Tempo) "
        "accepting? `arip preflight` will show you the per-signal coverage."
    ),
    "no_rule_matched": (
        "ARIP has rules for 5 specific failure shapes (retry_storm, "
        "db_pool_exhaustion, downstream_error, concurrent_modification, "
        "latency_vs_db). This failure didn't match any. Either the underlying "
        "issue is genuinely outside the 5 rules' scope, OR your telemetry is "
        "missing signals one of them needs (e.g. retry.attempt attribute, "
        "db.pool.* stats). See docs/INVESTIGATION_RULES.md per-rule contracts."
    ),
    "weak_evidence": (
        "A rule almost fired but ARIP needs ≥ 2 distinct evidence kinds "
        "(spans + logs, or spans + span_events) to promote it past abstention. "
        "Most likely cause: spans are present but correlated logs aren't joined "
        "into the bundle. Add log_trace_correlation: run "
        "bin/loki-export-to-logs.py (or the Elasticsearch equivalent) to join "
        "logs by trace_id. See docs/INGESTION_GUIDE.md Workflow 2."
    ),
    "conflicting_hypotheses": (
        "Two rules fired with similar confidence on disjoint evidence. ARIP "
        "won't pick one — that would risk sending you in the wrong direction. "
        "Investigate the candidates manually; the right answer is probably "
        "either both (a cascade) or neither (a third unidentified cause). "
        "See docs/abstention-gallery.md."
    ),
}


@dataclass
class AbstentionReason:
    code: str  # 'no_primary_trace' | 'empty_telemetry' | 'no_rule_matched' | 'weak_evidence' | 'conflicting_hypotheses'
    headline: str
    detail: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def next_step(self) -> str:
        """Operator-facing actionable hint for closing the gap that
        produced this abstention. Templated per abstention code so
        it's consistent across reports."""
        return _NEXT_STEPS.get(self.code, "")


def evaluate_abstention(
    ct: CorrelatedTelemetry,
    hypotheses: list[Hypothesis],
) -> AbstentionReason | None:
    """Return an abstention reason if the engine should NOT promote a
    primary hypothesis, otherwise None."""
    has_primary_trace = any(s.trace_id == ct.primary_trace_id for s in ct.spans)

    if not has_primary_trace:
        return AbstentionReason(
            code="no_primary_trace",
            headline="Primary trace not found in the telemetry backend.",
            detail=(
                "The failure carries a trace_id but no spans for that trace "
                "were retrievable from Jaeger after a bounded retry. The trace "
                "may have been sampled out, lost in the pipeline, or not yet "
                "flushed by the SDK. Without the primary trace, any hypothesis "
                "would be speculative."
            ),
            diagnostics={
                "expected_trace_id": ct.primary_trace_id,
                "spans_seen": len(ct.spans),
                "related_trace_ids": ct.related_trace_ids,
            },
        )

    if not ct.spans and not ct.logs:
        return AbstentionReason(
            code="empty_telemetry",
            headline="No spans or logs available for the failure window.",
            detail=(
                "The telemetry backends returned no data for the failure's "
                "time window. Common causes: services not instrumented, "
                "telemetry pipeline down, or aggressive sampling."
            ),
        )

    if not hypotheses:
        return AbstentionReason(
            code="no_rule_matched",
            headline="No deterministic rule matched this telemetry shape.",
            detail=(
                "The investigation engine has rules covering known failure "
                "patterns (concurrent modification, downstream error, "
                "application-layer latency). None matched. This may be a "
                "novel pattern; consider adding a rule, or escalate to a human."
            ),
            diagnostics={
                "spans": len(ct.spans),
                "logs": len(ct.logs),
                "db_queries": len(ct.db_queries),
            },
        )

    # Conflict detection: multiple rules firing on materially different
    # parts of the trace, at similar confidence. ARIP declines rather
    # than picking one — better to surface the ambiguity than to
    # nominate a primary an engineer would chase the wrong direction on.
    conflict = _detect_conflict(hypotheses)
    if conflict is not None:
        a, b, overlap = conflict
        return AbstentionReason(
            code="conflicting_hypotheses",
            headline="Multiple plausible but conflicting explanations.",
            detail=(
                f"Two or more rules fired with similar confidence on "
                f"disjoint evidence. `{a.rule_id}` (conf {a.confidence:.2f}) "
                f"and `{b.rule_id}` (conf {b.confidence:.2f}) cite "
                f"different parts of the trace ({overlap:.0%} evidence "
                f"overlap). Each is a real signal; ARIP declines to "
                f"promote one as primary because a wrong choice would "
                f"send an engineer in the wrong direction. All candidate "
                f"findings are listed below — weigh them by hand."
            ),
            diagnostics={
                "candidates": [
                    {"rule_id": h.rule_id, "confidence": h.confidence, "title": h.title}
                    for h in hypotheses[:4]
                ],
                "evidence_overlap": overlap,
            },
        )

    top = hypotheses[0]
    distinct_kinds = {e.kind for e in top.evidence}
    if top.confidence < WEAK_CONFIDENCE_CEILING or len(distinct_kinds) < MIN_EVIDENCE_KINDS:
        return AbstentionReason(
            code="weak_evidence",
            headline="Top hypothesis lacks corroborating evidence.",
            detail=(
                f"The best-matching rule produced a hypothesis "
                f"`{top.title}` with confidence {top.confidence:.2f} and "
                f"{len(distinct_kinds)} kind(s) of evidence. ARIP abstains "
                f"from promoting weak hypotheses to primary status; the "
                f"finding is listed as a candidate only."
            ),
            diagnostics={
                "candidate_title": top.title,
                "candidate_confidence": top.confidence,
                "evidence_kinds": sorted(distinct_kinds),
            },
        )

    return None


def _detect_conflict(
    hypotheses: list[Hypothesis],
) -> tuple[Hypothesis, Hypothesis, float] | None:
    """Detect two top hypotheses pointing at materially different parts
    of the trace at similar confidence. Returns ``(a, b, overlap)`` or
    ``None``.
    """
    if len(hypotheses) < 2:
        return None
    a = hypotheses[0]
    if a.confidence < CONFLICT_MIN_CONFIDENCE:
        return None
    # If the top hypothesis is already highly confident, the rule's
    # own corroboration signals were strong. Don't second-guess by
    # abstaining — that would just hide a good finding.
    if a.confidence >= CONFLICT_TOP_CONFIDENCE_CEILING:
        return None
    for b in hypotheses[1:]:
        if b.confidence < CONFLICT_MIN_CONFIDENCE:
            continue
        if a.confidence - b.confidence >= CONFLICT_DELTA:
            # b is meaningfully weaker; a clearly wins, no conflict.
            continue
        # Both hypotheses must be well-grounded (≥ 2 evidence kinds)
        # before we treat them as serious enough to conflict.
        if len({e.kind for e in a.evidence}) < 2:
            continue
        if len({e.kind for e in b.evidence}) < 2:
            continue
        overlap = _evidence_overlap(a, b)
        if overlap < CONFLICT_MAX_OVERLAP:
            return a, b, overlap
    return None


def _evidence_overlap(a: Hypothesis, b: Hypothesis) -> float:
    """Jaccard similarity between the (span_id ∪ log-message) sets of
    two hypotheses' cited evidence. 1.0 means identical evidence; 0.0
    means completely disjoint."""

    def keys(h: Hypothesis) -> set[str]:
        out: set[str] = set()
        for e in h.evidence:
            if e.span_id:
                out.add(f"span:{e.span_id}")
            if e.kind == "log" and e.description:
                # log descriptions are stable ("payment: order in unexpected
                # state during confirmation"), so use them as identifiers.
                out.add(f"log:{e.description}")
        return out

    ka, kb = keys(a), keys(b)
    if not ka or not kb:
        return 0.0
    inter = len(ka & kb)
    union = len(ka | kb)
    return inter / union if union else 0.0
