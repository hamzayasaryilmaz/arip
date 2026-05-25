"""Base class for deterministic investigation rules.

A rule receives the full ``CorrelatedTelemetry`` and returns zero or
more ``Hypothesis`` objects. Rules MUST be deterministic — given the
same telemetry they MUST produce the same output. No LLM, no
randomness, no time-dependent logic beyond what's already in the data.
"""

from __future__ import annotations

from typing import Protocol

from ...correlator.models import CorrelatedTelemetry
from ..models import Hypothesis


class Rule(Protocol):
    rule_id: str

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]: ...


def jaeger_link(trace_id: str, base: str = "http://localhost:16686") -> str:
    return f"{base}/trace/{trace_id}"
