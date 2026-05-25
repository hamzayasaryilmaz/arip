"""Shared dataclasses produced by the correlator and consumed by every
later stage of the pipeline. These mirror the Phase 3 contract in the
master prompt's ``CorrelatedTelemetry`` shape, with a couple of
additions that make the demo more useful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..canonical.config import NormalizationConfig
from ..canonical.signals import Signals
from ..collector.failure_event import FailureEvent


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service_name: str
    operation_name: str
    start_time: datetime
    duration_us: int
    status: str  # "OK" or "ERROR"
    status_message: str
    attributes: dict[str, Any]
    events: list[dict[str, Any]]

    @property
    def end_time(self) -> datetime:
        return datetime.fromtimestamp(
            self.start_time.timestamp() + (self.duration_us / 1_000_000),
            tz=self.start_time.tzinfo,
        )

    @property
    def is_error(self) -> bool:
        return self.status == "ERROR"

    @property
    def is_db(self) -> bool:
        """Default heuristic preserved for backward compatibility.
        Rules should prefer ``ct.signals.is_db_span(span)`` so the
        check is config-driven."""
        return self.operation_name.startswith("db.") or "db.system" in self.attributes


@dataclass
class LogEntry:
    timestamp: datetime
    service_name: str
    level: str
    message: str
    trace_id: str | None
    fields: dict[str, Any]


@dataclass
class DBQuery:
    """A DB operation, derived from a ``db.*`` span. We don't need a
    separate Postgres client to expose this — the OTel ``db.*`` span
    already carries duration, system, table, and operation."""

    timestamp: datetime
    service_name: str
    operation: str  # e.g. "UPDATE"
    table: str
    duration_us: int
    trace_id: str
    span_id: str


@dataclass
class K8sEvent:
    """Placeholder. The demo runs on Docker Compose; a Kubernetes-aware
    correlator can populate this in a follow-up."""

    timestamp: datetime
    reason: str
    message: str
    involved_object: str


@dataclass
class TimelineItem:
    timestamp: datetime
    kind: str  # 'span_start' | 'span_event' | 'log' | 'db_query'
    service: str
    summary: str
    detail: dict[str, Any]


@dataclass
class CorrelatedTelemetry:
    """Everything the engine needs to reason about a failure."""

    failure: FailureEvent
    logs: list[LogEntry]
    spans: list[Span]
    k8s_events: list[K8sEvent]
    db_queries: list[DBQuery]
    timeline: list[TimelineItem]

    # Additions beyond the spec shape:
    primary_trace_id: str
    related_trace_ids: list[str] = field(default_factory=list)
    order_id: str | None = None

    # Normalization config — controls how raw telemetry maps to canonical
    # signals. Default matches the demo stack's conventions exactly, so
    # existing tests and scenarios do not regress.
    normalization_config: NormalizationConfig = field(default_factory=NormalizationConfig)

    @property
    def signals(self) -> Signals:
        """Config-aware accessor over canonical telemetry. Rules read
        through this rather than touching ``span.attributes`` directly."""
        return Signals(self.normalization_config)
