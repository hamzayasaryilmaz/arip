"""Fingerprint computation for observation events.

Two regimes:

  - Rule-grounded:   primary hypothesis exists. Fingerprint reuses
                     `memory.fingerprint.fingerprint_hypothesis` exactly,
                     so a production-observed retry_storm shares a
                     fingerprint with a CI-investigated one.

  - Abstention-grounded: engine abstained. Fingerprint folds the
                     abstention code with the service-set and a
                     truncated operation-name sample. This lets us
                     count abstention recurrence ("`weak_evidence` on
                     `POST /checkout` for payment-service appeared 47
                     times") without claiming a root cause.

There is no third regime. If the engine produces neither a primary nor
an abstention (shouldn't happen by construction, but defensively), no
event is recorded.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

from ..correlator.models import CorrelatedTelemetry
from ..engine.abstention import AbstentionReason
from ..engine.hypothesis import InvestigationResult
from ..memory.fingerprint import fingerprint_hypothesis


def fingerprint_for_result(
    ct: CorrelatedTelemetry, result: InvestigationResult
) -> str | None:
    """Return a stable fingerprint or None if the result is unclusterable."""
    if result.primary is not None:
        return fingerprint_hypothesis(result.primary)
    if result.abstention is not None:
        return _abstention_fingerprint(ct, result.abstention)
    return None


def _abstention_fingerprint(
    ct: CorrelatedTelemetry, abstention: AbstentionReason
) -> str:
    """Abstention fingerprint = (code, entry_service_set).

    `entry_service_set` is the set of services that own *entry-point*
    spans (root spans, or spans whose parent_span_id is missing from
    the bundle — i.e. the user-facing edges of the trace). The full
    set of transitively-included services is recorded on the cluster
    as metadata but NOT in the fingerprint.

    Why this matters (validation finding from OTel Demo, op002):
    a 16-service mesh produces high-cardinality service_set
    combinations as different request paths touch different subsets.
    291 traces produced 23 distinct service-set combinations →
    23 abstention clusters from what should have been a much smaller
    number of distinct trace shapes. Clustering by entry-service
    collapses this back to the meaningful axis: which edge of the
    system originated the trace.

    Operation names are also NOT in the fingerprint, for the same
    high-cardinality reason (path parameters like /checkout/order-12345).
    The operation_names_sample is still recorded on the cluster as
    metadata.
    """
    entry_services = sorted(_entry_point_services(ct))
    parts = [
        f"abstention:{abstention.code}",
        "entry_services=" + ",".join(entry_services),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _entry_point_services(ct: CorrelatedTelemetry) -> set[str]:
    """Services that own root spans (parent_span_id is None or points
    outside the bundle). Falls back to all services if heuristic
    yields nothing."""
    span_ids = {s.span_id for s in ct.spans}
    entries = {
        s.service_name
        for s in ct.spans
        if s.service_name
        and (not s.parent_span_id or s.parent_span_id not in span_ids)
    }
    if entries:
        return entries
    # Fallback: if no clear entry-point heuristic matches, use all
    # services. This preserves the prior behaviour for trace shapes
    # where every span has a parent that's also in the bundle (rare).
    return {s.service_name for s in ct.spans if s.service_name}


def service_set(ct: CorrelatedTelemetry) -> tuple[str, ...]:
    return tuple(sorted({s.service_name for s in ct.spans if s.service_name}))


def operation_names(ct: CorrelatedTelemetry, limit: int = 8) -> tuple[str, ...]:
    return tuple(sorted({s.operation_name for s in ct.spans if s.operation_name}))[:limit]


def evidence_kinds(result: InvestigationResult) -> tuple[str, ...]:
    """Evidence kinds across the primary (if any) or all candidates."""
    candidates: Iterable = (
        [result.primary] if result.primary else result.all_ranked
    )
    kinds: set[str] = set()
    for h in candidates:
        if h is None:
            continue
        for e in h.evidence:
            kinds.add(e.kind)
    return tuple(sorted(kinds))
