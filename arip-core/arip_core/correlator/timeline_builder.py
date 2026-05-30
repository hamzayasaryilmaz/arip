"""Build a single ``CorrelatedTelemetry`` for a ``FailureEvent``.

What it does, end to end:

  1. Pulls the failure's primary trace from Jaeger.
  2. If the failure carries an ``order_id``, asks Jaeger for any other
     traces that touched the same order (this is how the
     ``webhook_race`` failure is correlated across two traces).
  3. Pulls service logs around the failure's timeframe and filters
     them by trace_id.
  4. Lifts ``db.*`` spans into first-class ``DBQuery`` rows so the
     engine can reason about them without re-doing span shape inspection.
  5. Folds spans, span events, logs, and DB queries into a single
     timestamp-ordered timeline.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from ..canonical.config import NormalizationConfig
from ..canonical.signals import Signals
from ..collector.failure_event import FailureEvent
from .docker_logs_client import DockerLogsClient
from .jaeger_client import JaegerClient
from .models import (
    CorrelatedTelemetry,
    DBQuery,
    LogEntry,
    Span,
    TimelineItem,
)

log = logging.getLogger(__name__)


class TimelineBuilder:
    def __init__(
        self,
        jaeger: JaegerClient,
        logs: DockerLogsClient,
        window: timedelta = timedelta(seconds=30),
        config: NormalizationConfig | None = None,
    ) -> None:
        self.jaeger = jaeger
        self.logs = logs
        self.window = window
        # Config-driven canonical-signal lookups. Default = demo
        # conventions, so existing scenarios are unchanged.
        self.config = config or NormalizationConfig()

    def build(self, failure: FailureEvent) -> CorrelatedTelemetry:
        # Use retry for the primary trace — it may not have flushed yet
        # if investigation runs immediately after the test failed.
        primary_spans = self.jaeger.get_trace_with_retry(failure.trace_id)
        if not primary_spans:
            log.warning(
                "primary trace %s never appeared in jaeger; continuing with empty trace",
                failure.trace_id,
            )
        order_id = (
            failure.test_metadata.get("annotations", {}).get("order_id")
            if failure.test_metadata
            else None
        )

        related_ids: list[str] = []
        related_spans: list[Span] = []
        if order_id:
            # Query EVERY configured business_key attribute (canonical +
            # aliases). Handles ID-translation chains where the same
            # logical key has different names across services.
            from ..canonical.signals import Signals

            tag_attrs = Signals(self.config).all_business_key_attrs() or ["order.id"]
            for svc in ("payment-service", "inventory-service"):
                for tag_attr in tag_attrs:
                    try:
                        found = self.jaeger.find_traces_by_tag(svc, tag_attr, order_id)
                    except Exception as exc:
                        log.warning("find_traces_by_tag(%s, %s) failed: %s", svc, tag_attr, exc)
                        continue
                    for tid in found:
                        if tid != failure.trace_id and tid not in related_ids:
                            related_ids.append(tid)
        for tid in related_ids:
            try:
                related_spans.extend(self.jaeger.get_trace(tid))
            except Exception as exc:
                log.warning("get_trace(%s) failed: %s", tid, exc)

        spans = primary_spans + related_spans

        since, until = self._window_for(spans, failure)
        trace_ids = [failure.trace_id, *related_ids]
        try:
            log_entries = self.logs.fetch(since=since, until=until, trace_ids=trace_ids)
        except Exception as exc:
            log.warning("log fetch failed: %s", exc)
            log_entries = []

        signals = Signals(self.config)
        db_queries = _db_queries_from(spans, signals)
        timeline = _build_timeline(spans, log_entries, db_queries)

        return CorrelatedTelemetry(
            failure=failure,
            logs=log_entries,
            spans=spans,
            k8s_events=[],
            db_queries=db_queries,
            timeline=timeline,
            primary_trace_id=failure.trace_id,
            related_trace_ids=related_ids,
            order_id=order_id,
            normalization_config=self.config,
        )

    def _window_for(self, spans: list[Span], failure: FailureEvent) -> tuple[datetime, datetime]:
        if spans:
            start = min(s.start_time for s in spans)
            end = max(s.end_time for s in spans)
        else:
            start = end = failure.timestamp
        return (start - self.window, end + self.window)


def _db_queries_from(spans: Iterable[Span], signals: Signals) -> list[DBQuery]:
    out: list[DBQuery] = []
    for s in spans:
        if not signals.is_db_span(s):
            continue
        out.append(
            DBQuery(
                timestamp=s.start_time,
                service_name=s.service_name,
                operation=str(s.attributes.get("db.operation", s.operation_name)),
                table=str(s.attributes.get("db.sql.table", "")),
                duration_us=s.duration_us,
                trace_id=s.trace_id,
                span_id=s.span_id,
            )
        )
    return out


def _build_timeline(
    spans: list[Span],
    log_entries: list[LogEntry],
    db_queries: list[DBQuery],
) -> list[TimelineItem]:
    items: list[TimelineItem] = []

    for s in spans:
        items.append(
            TimelineItem(
                timestamp=s.start_time,
                kind="span_start",
                service=s.service_name,
                summary=f"{s.operation_name} ({s.duration_us / 1000:.1f}ms){' ERROR' if s.is_error else ''}",
                detail={
                    "trace_id": s.trace_id,
                    "span_id": s.span_id,
                    "duration_us": s.duration_us,
                    "status": s.status,
                    "status_message": s.status_message,
                    "attributes": s.attributes,
                },
            )
        )
        for ev in s.events:
            ts = ev.get("timestamp")
            if not isinstance(ts, datetime):
                continue
            name = str(ev.get("fields", {}).get("event", "")) or "event"
            items.append(
                TimelineItem(
                    timestamp=ts,
                    kind="span_event",
                    service=s.service_name,
                    summary=f"span event: {name}",
                    detail={"span_id": s.span_id, "fields": ev.get("fields", {})},
                )
            )

    for entry in log_entries:
        items.append(
            TimelineItem(
                timestamp=entry.timestamp,
                kind="log",
                service=entry.service_name,
                summary=f"[{entry.level}] {entry.message}",
                detail={"trace_id": entry.trace_id, "fields": entry.fields},
            )
        )

    for q in db_queries:
        items.append(
            TimelineItem(
                timestamp=q.timestamp,
                kind="db_query",
                service=q.service_name,
                summary=f"{q.operation} {q.table} ({q.duration_us / 1000:.1f}ms)",
                detail={"trace_id": q.trace_id, "span_id": q.span_id},
            )
        )

    items.sort(key=lambda i: (i.timestamp, 0 if i.kind == "span_start" else 1))
    return items


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
