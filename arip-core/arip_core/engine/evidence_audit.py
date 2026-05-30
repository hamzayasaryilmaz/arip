"""Verify that every cited Evidence reference exists in the telemetry.

Defensive: if a rule cites span_id `abc` but no such span exists in the
correlated telemetry, that's a rule bug or hallucinated reference. We
drop the evidence and downgrade the hypothesis's confidence proportionally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from ..correlator.models import CorrelatedTelemetry
from .models import Evidence, Hypothesis

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditResult:
    dropped_evidence: list[Evidence]
    kept_evidence: list[Evidence]


def audit_and_clean(ct: CorrelatedTelemetry, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Return hypotheses with verifiably-grounded evidence only.

    Strategy:
      * If an evidence cites a trace_id, that trace_id must appear in
        the correlated spans (or related_trace_ids).
      * If it cites a span_id, that span must exist.
      * Failed evidence is dropped, not silently kept.
      * If a hypothesis loses ALL evidence, it is dropped from the
        returned list — unsupported claims are not surfaced.
      * Confidence is decayed proportionally to how much evidence was lost.
    """
    known_trace_ids = (
        {s.trace_id for s in ct.spans} | set(ct.related_trace_ids) | {ct.primary_trace_id}
    )
    known_span_ids = {s.span_id for s in ct.spans}
    # Logs we can't reliably "address by id" — they're whole records.
    # We trust log evidence as long as the (service, message) combination
    # appears in ct.logs.
    log_index = {(l.service_name, l.message) for l in ct.logs}

    out: list[Hypothesis] = []
    for h in hypotheses:
        result = _audit_hypothesis(h, known_trace_ids, known_span_ids, log_index)
        if not result.kept_evidence:
            log.warning(
                "rule %r produced %d evidence items but none were verifiable; dropping hypothesis",
                h.rule_id,
                len(h.dropped_evidence) if hasattr(h, "dropped_evidence") else 0,
            )
            continue
        if result.dropped_evidence:
            decay = 1.0 - 0.5 * (len(result.dropped_evidence) / max(1, len(h.evidence)))
            new_conf = max(0.0, h.confidence * decay)
            log.warning(
                "rule %r dropped %d/%d evidence items; confidence %0.2f -> %0.2f",
                h.rule_id,
                len(result.dropped_evidence),
                len(h.evidence),
                h.confidence,
                new_conf,
            )
            out.append(replace(h, evidence=result.kept_evidence, confidence=new_conf))
        else:
            out.append(h)
    return out


def _audit_hypothesis(
    h: Hypothesis,
    known_trace_ids: set,
    known_span_ids: set,
    log_index: set,
) -> AuditResult:
    kept: list[Evidence] = []
    dropped: list[Evidence] = []
    for ev in h.evidence:
        if _is_grounded(ev, known_trace_ids, known_span_ids, log_index):
            kept.append(ev)
        else:
            dropped.append(ev)
    return AuditResult(dropped_evidence=dropped, kept_evidence=kept)


def _is_grounded(
    ev: Evidence,
    known_trace_ids: set,
    known_span_ids: set,
    log_index: set,
) -> bool:
    # Log evidence: must match a real log line by (service, message).
    if ev.kind == "log":
        return (ev.service, ev.description.split(": ", 1)[-1]) in log_index or any(
            ev.description.endswith(msg) for (_, msg) in log_index
        )
    # Span / span_event / db_query: anchor must exist.
    if ev.span_id and ev.span_id not in known_span_ids:
        return False
    if ev.trace_id and ev.trace_id not in known_trace_ids:
        return False
    # Without either an id or a log match, we can't ground it.
    return bool(ev.trace_id or ev.span_id)
