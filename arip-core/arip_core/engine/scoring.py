"""Pick the primary hypothesis and order the rest as alternatives.

Ranking: severity bucket first, then confidence. Hypotheses with no
evidence are dropped — the engine never reports unsupported claims.
"""

from __future__ import annotations

from .models import Hypothesis


def rank_hypotheses(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    supported = [h for h in hypotheses if h.evidence]
    return sorted(supported, key=lambda h: h.rank, reverse=True)
