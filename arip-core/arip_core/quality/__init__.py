"""Telemetry quality scoring + per-rule contracts.

This package is diagnostic, not corrective. It tells you how good the
input telemetry is and which rules are likely to fire — it never
changes a rule's behaviour. Engine remains deterministic.
"""

from .assessment import (
    QualityAssessment,
    QualityFinding,
    SignalCoverage,
    assess,
)
from .contracts import RULE_CONTRACTS, RuleContract, contracts_for_rule

__all__ = [
    "RULE_CONTRACTS",
    "QualityAssessment",
    "QualityFinding",
    "RuleContract",
    "SignalCoverage",
    "assess",
    "contracts_for_rule",
]
