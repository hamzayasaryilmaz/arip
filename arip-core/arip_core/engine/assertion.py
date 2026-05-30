"""Assertion-aware confidence adjustment.

A test's assertion tells us what kind of invariant it cared about.
Rules whose root-cause story aligns with that kind of invariant are
slightly more likely to be the actually-causal explanation; rules
whose story aligns with a *different* kind are slightly less likely.

This is a tiny deterministic heuristic — keyword-based, no NLP, no
LLM. Boost / decay is intentionally small (±0.03) so it nudges
ranking without overriding the rule's own confidence formula.
"""

from __future__ import annotations

from dataclasses import replace

from .models import Hypothesis

# What an assertion's free-text typically signals.
_LATENCY_KEYS = ("ms", "sla", "latency", "within", "second", "timeout", "complete in", "respond")
_STATUS_KEYS = ("status", "200", "503", "5xx", "4xx", "success", "returns", "returned", "ok ")
_CORRECTNESS_KEYS = (
    "interleaved",
    "consistent",
    "race",
    "history",
    "invariant",
    "transition",
    "state ",
)
_RETRY_KEYS = ("retry", "retries", "attempt", "exhaust")

# Which rule's signature aligns with which assertion category.
RULE_ALIGNMENT: dict[str, set[str]] = {
    "latency_vs_db": {"latency"},
    "db_pool_exhaustion": {"latency", "status"},
    "downstream_error": {"status"},
    "retry_storm": {"status", "retry"},
    "concurrent_modification": {"correctness"},
}


def classify_assertion(assertion: str) -> set[str]:
    """Return a set of tags describing what the test asserted.

    Multiple tags are valid; ``status`` and ``latency`` often co-occur
    in the same assertion. An empty set means "no signal" — the
    adjuster will leave confidence unchanged in that case.
    """
    if not assertion:
        return set()
    a = assertion.lower()
    tags: set[str] = set()
    if any(k in a for k in _LATENCY_KEYS):
        tags.add("latency")
    if any(k in a for k in _STATUS_KEYS):
        tags.add("status")
    if any(k in a for k in _CORRECTNESS_KEYS):
        tags.add("correctness")
    if any(k in a for k in _RETRY_KEYS):
        tags.add("retry")
    return tags


def adjust_for_assertion(
    hypotheses: list[Hypothesis],
    assertion: str,
    *,
    boost: float = 0.03,
) -> list[Hypothesis]:
    """Nudge each hypothesis's confidence based on whether its rule
    aligns with the assertion's category.

    Rules aligned with the assertion get +boost; misaligned rules get
    -boost. Both are clamped to ``[0.0, 0.95]``. Boost magnitude is
    small by design — this is a soft re-ranking, not a re-write.
    """
    tags = classify_assertion(assertion)
    if not tags:
        return hypotheses
    out: list[Hypothesis] = []
    for h in hypotheses:
        rule_tags = RULE_ALIGNMENT.get(h.rule_id or "", set())
        if rule_tags & tags:
            new_conf = min(h.confidence + boost, 0.95)
        elif rule_tags:
            # Rule has known alignment but it doesn't match this assertion.
            new_conf = max(h.confidence - boost, 0.0)
        else:
            new_conf = h.confidence
        out.append(replace(h, confidence=round(new_conf, 2)))
    return out
