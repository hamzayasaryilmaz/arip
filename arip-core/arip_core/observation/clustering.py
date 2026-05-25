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
    """Abstention fingerprint = (code, service_set).

    Operation names are deliberately NOT in the fingerprint. Production
    operation names frequently carry high-cardinality path parameters
    (`POST /checkout/order-12345`) or auto-generated tokens; including
    them splits every observation into its own singleton cluster,
    making the abstention digest unreadable under real-world noise.
    The operation_names_sample is still recorded on the AnomalyCluster
    for operator context, just not as a fingerprint determinant.
    """
    services = sorted({s.service_name for s in ct.spans if s.service_name})
    parts = [
        f"abstention:{abstention.code}",
        "services=" + ",".join(services),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


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
