"""Deterministic fingerprint for a hypothesis.

Two investigations with the "same root cause shape" should share a
fingerprint regardless of trace_ids, order_ids, or timestamps. The
fingerprint is what lets us say "we've seen this 7 times in the last
14 days" — the cornerstone of cross-run intelligence.

What goes into the fingerprint:
    * rule_id              (which rule produced it)
    * sorted service set   (which services were named in evidence)
    * sorted evidence-kind SET (which kinds participated, not how many)

What deliberately does NOT go in:
    * trace_id, span_id, order_id (vary per run)
    * timestamps
    * free-text descriptions (vary slightly per run)
    * confidence (post-fingerprint signal)
    * evidence-kind MULTIPLICITY (count of spans/logs cited)

The multiplicity exclusion is deliberate. A retry storm with 3 attempts
and one with 5 attempts cite different numbers of span Evidence rows
but represent the same anomaly shape. Counting that multiplicity into
the fingerprint splits a single recurring pattern into N fingerprints,
defeating cross-run aggregation under realistic noise. Membership
captures "logs corroborated" vs "spans only" — which IS a fingerprint
signal — without that fragmentation.
"""

from __future__ import annotations

import hashlib

from ..engine.models import Hypothesis


def fingerprint_hypothesis(h: Hypothesis) -> str:
    """Return a stable 16-char hex fingerprint for a hypothesis."""
    services = sorted({ev.service for ev in h.evidence if ev.service})
    kinds = sorted({ev.kind for ev in h.evidence})
    parts = [
        h.rule_id or "",
        "|services=" + ",".join(services),
        "|kinds=" + ",".join(kinds),
    ]
    digest = hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
