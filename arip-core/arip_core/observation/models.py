"""Canonical shapes for observation-mode telemetry."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ..quality.prerequisite import PrerequisiteFailure


@dataclass(frozen=True)
class CanonicalAnomalyEvent:
    """One observation processed through the engine.

    The trace_id is stored as a hash to keep production trace identifiers
    out of the local store — observation mode does not need to read raw
    trace_ids back out, only count and correlate them. The hash is
    deterministic so duplicate observations of the same trace collapse.
    """

    source_name: str
    observation_id: str
    trace_id_hash: str
    fingerprint: str
    observed_at: datetime
    rule_id: str | None
    abstention_code: str | None
    quality_band: str  # 'high' | 'medium' | 'low'
    quality_score: float
    primary_confidence: float | None
    service_set: tuple[str, ...]
    operation_names: tuple[str, ...]
    evidence_kinds: tuple[str, ...]


@dataclass
class AnomalyCluster:
    """A group of observations sharing the same fingerprint.

    A cluster is rule-grounded (rule_id is set) OR abstention-grounded
    (abstention_code is set). Never both. This is the only structural
    invariant — clustering is otherwise just bookkeeping over the engine's
    own decisions.
    """

    fingerprint: str
    rule_id: str | None
    abstention_code: str | None
    first_seen: datetime
    last_seen: datetime
    recurrence_count: int
    dominant_quality_band: str
    service_set: tuple[str, ...]
    operation_names_sample: tuple[str, ...]
    example_trace_id_hash: str


@dataclass
class ObservationSummary:
    """Per-run summary: what one `arip observe` invocation processed."""

    source_name: str
    window_label: str
    started_at: datetime
    finished_at: datetime
    traces_observed: int
    events_new: int
    events_skipped_idempotent: int
    cursor_before: str | None
    cursor_after: str | None
    quality_band_counts: dict[str, int] = field(default_factory=dict)
    abstention_code_counts: dict[str, int] = field(default_factory=dict)
    rule_match_counts: dict[str, int] = field(default_factory=dict)
    # Set when the FIRST observed trace failed the telemetry prerequisite
    # check (no spans / no trace_id / no propagation). Pipeline aborts
    # the rest of the source rather than running the engine on telemetry
    # that does not meet the distributed-tracing baseline.
    prerequisite_failure: PrerequisiteFailure | None = None
    # Telemetry-hygiene findings derived from the trace bundles ARIP saw.
    # Populated by hardening checks (service-coverage, log-source
    # completeness, span-tree gaps). Operator-facing; not consumed by
    # the engine.
    hygiene_findings: list[str] = field(default_factory=list)


@dataclass
class ObservationDigest:
    """The rendered surface of observation mode.

    Built from the cluster store across a query window. Designed to be
    read by an engineer, not parsed. Markdown rendering lives in
    `digest.py`.
    """

    generated_at: datetime
    window_label: str
    summary: ObservationSummary | None
    rule_clusters: Sequence[AnomalyCluster]
    abstention_clusters: Sequence[AnomalyCluster]
    low_quality_count: int
    notes: Sequence[str] = field(default_factory=tuple)
