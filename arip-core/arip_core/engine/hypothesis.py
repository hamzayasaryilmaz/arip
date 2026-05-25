"""Run every rule against telemetry, audit evidence, rank what remains."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..correlator.models import CorrelatedTelemetry
from .abstention import AbstentionReason, evaluate_abstention
from .assertion import adjust_for_assertion
from .evidence_audit import audit_and_clean
from .models import Hypothesis
from .rules.base import Rule
from .rules.downstream_error import DownstreamErrorRule
from .rules.latency_vs_db import LatencyVsDBRule
from .rules.pool_exhaustion import PoolExhaustionRule
from .rules.retry_storm import RetryStormRule
from .rules.webhook_race import WebhookRaceRule
from .scoring import rank_hypotheses

log = logging.getLogger(__name__)


@dataclass
class InvestigationResult:
    primary: Hypothesis | None
    alternatives: list[Hypothesis]
    abstention: AbstentionReason | None
    all_ranked: list[Hypothesis]


def default_rules() -> list[Rule]:
    return [
        WebhookRaceRule(),
        RetryStormRule(),
        DownstreamErrorRule(),
        PoolExhaustionRule(),
        LatencyVsDBRule(),
    ]


def investigate(
    ct: CorrelatedTelemetry,
    rules: list[Rule] | None = None,
) -> InvestigationResult:
    """Run rules, audit evidence, rank, and decide whether to abstain.

    Pipeline:
      1. Each rule produces zero or more hypotheses.
      2. Evidence is audited against the actual telemetry — any
         hypothesis citing references that don't exist is dropped
         or downgraded.
      3. Remaining hypotheses are ranked by severity × confidence.
      4. Abstention is evaluated: when telemetry is missing, no rule
         matched, or the top hypothesis is weak, the engine declines
         to nominate a primary hypothesis.
    """
    rules = rules or default_rules()
    raw: list[Hypothesis] = []
    for rule in rules:
        try:
            raw.extend(rule.evaluate(ct))
        except Exception:
            log.exception("rule %s failed", rule.rule_id)

    audited = audit_and_clean(ct, raw)
    # Nudge confidence by how well each rule's category aligns with what
    # the test actually asserted (latency vs status vs correctness). Soft
    # re-ranking; does not override the rule's own confidence formula.
    adjusted = adjust_for_assertion(audited, ct.failure.assertion)
    ranked = rank_hypotheses(adjusted)

    abstention = evaluate_abstention(ct, ranked)
    if abstention is not None:
        return InvestigationResult(
            primary=None,
            alternatives=ranked,
            abstention=abstention,
            all_ranked=ranked,
        )

    return InvestigationResult(
        primary=ranked[0],
        alternatives=ranked[1:],
        abstention=None,
        all_ranked=ranked,
    )
