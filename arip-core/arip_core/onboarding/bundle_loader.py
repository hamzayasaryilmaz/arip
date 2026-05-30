"""Load JSONL trace bundles into in-memory CorrelatedTelemetry instances.

Both `arip init` and `arip doctor` operate on a bundle file (the same
JSONL shape produced by `bin/*-export-to-bundles.py`) — they need the
spans and logs as objects, not raw dicts.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..canonical.config import NormalizationConfig
from ..collector.failure_event import FailureEvent
from ..correlator.models import CorrelatedTelemetry, LogEntry, Span


def _parse_dt(s: str | None) -> datetime:
    if not s:
        return datetime.fromtimestamp(0)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.fromtimestamp(0)


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt")
    return path.open("r")


def iter_bundles(path: Path) -> Iterator[dict[str, Any]]:
    """Yield each JSONL bundle dict from `path` (gzip-aware)."""
    with _open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _span(d: dict[str, Any]) -> Span:
    return Span(
        trace_id=d["trace_id"],
        span_id=d["span_id"],
        parent_span_id=d.get("parent_span_id"),
        service_name=d.get("service_name", "unknown"),
        operation_name=d.get("operation_name", ""),
        start_time=_parse_dt(d.get("start_time")),
        duration_us=int(d.get("duration_us", 0) or 0),
        status=d.get("status", "OK"),
        status_message=d.get("status_message", "") or "",
        attributes=d.get("attributes", {}) or {},
        events=d.get("events", []) or [],
    )


def _log(d: dict[str, Any]) -> LogEntry:
    return LogEntry(
        timestamp=_parse_dt(d.get("timestamp")),
        service_name=d.get("service_name", "unknown"),
        level=d.get("level", "INFO"),
        message=d.get("message", ""),
        trace_id=d.get("trace_id"),
        fields=d.get("fields", {}) or {},
    )


def load_correlated(
    path: Path,
    config: NormalizationConfig | None = None,
    limit: int | None = None,
) -> list[CorrelatedTelemetry]:
    """Load `path` as a list of CorrelatedTelemetry, one per bundle.

    Each bundle's spans + logs are wrapped in a minimal
    `CorrelatedTelemetry` so the engine and quality assessors can run
    against them. `failure` is a synthetic placeholder — onboarding
    is not investigating a real failure, it's introspecting telemetry
    shape.
    """
    cfg = config or NormalizationConfig()
    out: list[CorrelatedTelemetry] = []
    for i, b in enumerate(iter_bundles(path)):
        if limit is not None and i >= limit:
            break
        spans = [_span(s) for s in b.get("spans", []) if isinstance(s, dict)]
        logs = [_log(l) for l in b.get("logs", []) if isinstance(l, dict)]
        captured = _parse_dt(b.get("captured_at"))
        trace_id = b.get("trace_id", "")
        out.append(
            CorrelatedTelemetry(
                failure=FailureEvent(
                    test_name=f"onboarding:{trace_id[:10]}",
                    timestamp=captured,
                    environment="onboarding",
                    trace_id=trace_id,
                    assertion="",
                    error_message="",
                ),
                logs=logs,
                spans=spans,
                k8s_events=[],
                db_queries=[],
                timeline=[],
                primary_trace_id=trace_id,
                related_trace_ids=[],
                order_id=None,
                normalization_config=cfg,
            )
        )
    return out
