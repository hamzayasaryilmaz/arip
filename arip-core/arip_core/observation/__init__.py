"""Observation mode — Phase A.

Continuous, incremental, read-only observation of production-style
telemetry. Reuses the existing 5-rule deterministic engine and abstention
layer; produces no candidate tests, no PRs, no auto-anything.

Contract:
  - read-only ingestion (no mutation of sources)
  - cursor-based (resumable; no full-history rescan)
  - bounded per pull (memory + recency)
  - idempotent per (source_name, observation_id)
  - same engine path as `arip investigate`; observation events are not
    a parallel reasoning system

What this module DOES NOT do (intentionally, Phase A scope):
  - generate candidate reproduction tests
  - open PRs
  - run any sandbox or replay
  - emit alerts
  - score impact / page anyone
"""

from .models import (
    AnomalyCluster,
    CanonicalAnomalyEvent,
    ObservationDigest,
    ObservationSummary,
)

__all__ = [
    "AnomalyCluster",
    "CanonicalAnomalyEvent",
    "ObservationDigest",
    "ObservationSummary",
]
