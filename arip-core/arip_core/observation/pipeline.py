"""Observation pipeline.

For each `TraceObservation`:
  1. Build a minimal `CorrelatedTelemetry` (no related-trace fanout —
     observation mode does not synthesise cross-trace joins).
  2. Run the existing deterministic engine (same path as `arip
     investigate`). No parallel reasoning system, no LLM.
  3. Assess quality.
  4. Compute fingerprint via `clustering.fingerprint_for_result`.
  5. Persist event + upsert cluster (idempotent on observation_id).
  6. Save cursor after each successfully recorded observation.

The engine path is identical to investigation mode by design — that is
how observation events inherit the trust contract (evidence audit,
abstention discipline, conflict detection) without code duplication.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from ..canonical.config import NormalizationConfig
from ..collector.failure_event import FailureEvent
from ..correlator.models import CorrelatedTelemetry
from ..engine.hypothesis import investigate
from ..quality.assessment import assess as assess_quality
from .clustering import (
    evidence_kinds,
    fingerprint_for_result,
    operation_names,
    service_set,
)
from .models import CanonicalAnomalyEvent, ObservationSummary
from .sources.base import Source, TraceObservation
from .store import ObservationStore

log = logging.getLogger(__name__)


def observe(
    *,
    source: Source,
    store: ObservationStore,
    budget: int = 500,
    config: NormalizationConfig | None = None,
    window_label: str = "",
) -> ObservationSummary:
    """Drain up to `budget` observations from `source`; record them.

    Returns a per-run summary. Side effects are confined to `store`.
    `source` is never mutated.
    """
    config = config or NormalizationConfig()
    started = datetime.now(tz=UTC)
    cursor_before = store.load_cursor(source.name)
    cursor_after = cursor_before

    band_counts: dict[str, int] = {}
    abstention_counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    traces = 0
    new_events = 0
    skipped = 0

    def _advance_cursor(obs_cursor: str) -> None:
        """Update the in-memory + persisted cursor.

        Falls back to the previous value when the source emits an
        empty cursor (e.g. a malformed bundle the source still wants
        the pipeline to skip past). Does NOT persist None — that
        would crash the NOT NULL column. Silently skips the save
        when we have nothing meaningful to persist (first observation
        of a fresh source whose first bundle has no cursor).
        """
        nonlocal cursor_after
        candidate = obs_cursor or cursor_after
        if candidate is None:
            return
        cursor_after = candidate
        store.save_cursor(source.name, cursor_after)

    for obs in source.stream(cursor=cursor_before, budget=budget):
        traces += 1
        if not obs.spans:
            _advance_cursor(obs.cursor_after)
            continue
        try:
            ev = _observe_one(obs, store, config)
        except Exception:  # defensive — never let one bad trace stop the stream
            log.exception("observation failed for %s", obs.observation_id)
            _advance_cursor(obs.cursor_after)
            continue
        _advance_cursor(obs.cursor_after)
        if ev is None:
            skipped += 1
            continue
        new_events += 1
        band_counts[ev.quality_band] = band_counts.get(ev.quality_band, 0) + 1
        if ev.rule_id:
            rule_counts[ev.rule_id] = rule_counts.get(ev.rule_id, 0) + 1
        if ev.abstention_code:
            abstention_counts[ev.abstention_code] = abstention_counts.get(ev.abstention_code, 0) + 1

    finished = datetime.now(tz=UTC)
    return ObservationSummary(
        source_name=source.name,
        window_label=window_label,
        started_at=started,
        finished_at=finished,
        traces_observed=traces,
        events_new=new_events,
        events_skipped_idempotent=skipped,
        cursor_before=cursor_before,
        cursor_after=cursor_after,
        quality_band_counts=band_counts,
        abstention_code_counts=abstention_counts,
        rule_match_counts=rule_counts,
    )


def _observe_one(
    obs: TraceObservation,
    store: ObservationStore,
    config: NormalizationConfig,
) -> CanonicalAnomalyEvent | None:
    ct = _build_correlated_telemetry(obs, config)
    result = investigate(ct)
    fingerprint = fingerprint_for_result(ct, result)
    if fingerprint is None:
        # Engine produced neither a primary nor an abstention — should not
        # happen by construction. Skip rather than fabricate.
        return None

    quality = assess_quality(ct)
    rule_id = result.primary.rule_id if result.primary else None
    abstention_code = result.abstention.code if result.abstention else None
    primary_conf = result.primary.confidence if result.primary else None

    trace_hash = _hash_trace_id(obs.trace_id)

    event = CanonicalAnomalyEvent(
        source_name=obs.source_name,
        observation_id=obs.observation_id,
        trace_id_hash=trace_hash,
        fingerprint=fingerprint,
        observed_at=obs.observed_at or datetime.now(tz=UTC),
        rule_id=rule_id,
        abstention_code=abstention_code,
        quality_band=quality.confidence_band,
        quality_score=quality.score,
        primary_confidence=primary_conf,
        service_set=service_set(ct),
        operation_names=operation_names(ct),
        evidence_kinds=evidence_kinds(result),
    )

    inserted = store.record_event(event)
    if not inserted:
        return None  # idempotent skip
    store.upsert_cluster(event)
    return event


def _build_correlated_telemetry(
    obs: TraceObservation, config: NormalizationConfig
) -> CorrelatedTelemetry:
    failure = FailureEvent(
        test_name=f"observation:{_short(obs.source_name)}:{obs.trace_id[:12]}",
        timestamp=obs.observed_at or datetime.now(tz=UTC),
        environment="observation",
        trace_id=obs.trace_id,
        assertion="",
        error_message="",
    )
    return CorrelatedTelemetry(
        failure=failure,
        logs=list(obs.logs),
        spans=list(obs.spans),
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id=obs.trace_id,
        related_trace_ids=[],
        order_id=None,
        normalization_config=config,
    )


def _hash_trace_id(trace_id: str) -> str:
    return hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:16]


def _short(s: str, n: int = 32) -> str:
    return s if len(s) <= n else s[:n] + "…"
