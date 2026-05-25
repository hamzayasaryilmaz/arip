"""JSONL trace-bundle source.

Each line is a JSON object with `trace_id`, `spans`, optional `logs`,
optional `captured_at`. Transparent gzip support: `.jsonl.gz` files
are read as bytes and decoded line by line. Byte-offset cursor; survives
file appends as long as already-emitted lines aren't rewritten.

Example bundle:
    {
      "trace_id": "abc...",
      "captured_at": "2026-05-20T10:23:00Z",
      "spans": [
        {"trace_id": "abc...", "span_id": "...", "parent_span_id": null,
         "service_name": "payment-service", "operation_name": "POST /checkout",
         "start_time": "2026-05-20T10:23:00.001Z", "duration_us": 12000,
         "status": "ERROR", "status_message": "",
         "attributes": {"http.status_code": 500}, "events": []}
      ],
      "logs": [
        {"timestamp": "...", "service_name": "...", "level": "ERROR",
         "message": "...", "trace_id": "abc...", "fields": {}}
      ]
    }
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from ...correlator.models import LogEntry, Span
from .base import TraceObservation


class JsonlTraceSource:
    """Read-only stream over a JSONL or JSONL.GZ file of trace bundles.

    Cursor semantics: cursor is the *byte offset* in the (decompressed
    for .jsonl, raw for .jsonl) stream of the next byte to read. For
    `.jsonl.gz` the cursor is over the *uncompressed* stream so it
    remains stable across re-compression. We track gzipped streams by
    decompressing the prefix; this is bounded because callers move the
    cursor forward monotonically.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.name = f"jsonl://{self.path.resolve()}"
        self._gzipped = self.path.suffix == ".gz"

    def _open(self) -> BinaryIO:
        if self._gzipped:
            return gzip.open(self.path, "rb")
        return self.path.open("rb")

    def stream(
        self, *, cursor: str | None, budget: int
    ) -> Iterator[TraceObservation]:
        start = int(cursor) if cursor is not None else 0
        with self._open() as fh:
            # Both gzip.open and standard binary streams support .read(n).
            # We track byte offset over the *decoded* stream so the cursor
            # is meaningful for both file types.
            if start:
                # Advance past `start` bytes
                _advance(fh, start)
            offset = start
            yielded = 0
            for raw_line in fh:
                line_len = len(raw_line)
                line_stripped = raw_line.rstrip(b"\r\n")
                offset_after = offset + line_len
                if line_stripped:
                    try:
                        bundle = json.loads(line_stripped)
                    except json.JSONDecodeError:
                        # Bad line — skip but still advance cursor. We
                        # don't fail the whole stream on one malformed
                        # line; the operator will see this via warnings
                        # in the pipeline layer.
                        offset = offset_after
                        continue
                    obs = _bundle_to_observation(
                        bundle,
                        source_name=self.name,
                        line_start=offset,
                        line_end=offset_after,
                    )
                    if obs is not None:
                        yield obs
                        yielded += 1
                        if yielded >= budget:
                            return
                offset = offset_after


def _advance(fh: BinaryIO, n: int) -> None:
    """Skip n bytes from a stream. For gzip files seek is not always
    supported, so we read-and-discard in chunks."""
    if hasattr(fh, "seek"):
        try:
            fh.seek(n)
            return
        except (OSError, io.UnsupportedOperation):
            pass
    remaining = n
    while remaining > 0:
        chunk = fh.read(min(remaining, 65536))
        if not chunk:
            return
        remaining -= len(chunk)


def _bundle_to_observation(
    bundle: dict[str, Any],
    *,
    source_name: str,
    line_start: int,
    line_end: int,
) -> TraceObservation | None:
    trace_id = bundle.get("trace_id")
    if not trace_id:
        return None
    span_dicts = bundle.get("spans") or []
    if not span_dicts:
        # Empty trace — nothing for the engine to reason on. Skip but
        # the cursor still advances.
        return None
    spans: list[Span] = []
    for sd in span_dicts:
        sp = _span_from_dict(sd)
        if sp is not None:
            spans.append(sp)
    if not spans:
        return None
    log_dicts = bundle.get("logs") or []
    logs: list[LogEntry] = []
    for ld in log_dicts:
        lg = _log_from_dict(ld)
        if lg is not None:
            logs.append(lg)
    captured_at = _parse_dt(bundle.get("captured_at")) or _earliest(spans)
    observation_id = _stable_observation_id(
        source_name=source_name,
        trace_id=trace_id,
        line_start=line_start,
        span_signature=_span_signature(spans),
    )
    return TraceObservation(
        source_name=source_name,
        observation_id=observation_id,
        trace_id=trace_id,
        spans=spans,
        logs=logs,
        observed_at=captured_at,
        cursor_after=str(line_end),
    )


def _stable_observation_id(
    *, source_name: str, trace_id: str, line_start: int, span_signature: str
) -> str:
    """Idempotent ID per (source, trace, content).

    Includes a content signature so a re-published trace with mutated
    spans is a *different* observation; pure replays of the same content
    collapse onto the same observation_id and stay idempotent."""
    h = hashlib.sha256()
    h.update(source_name.encode("utf-8"))
    h.update(b"\0")
    h.update(trace_id.encode("utf-8"))
    h.update(b"\0")
    h.update(str(line_start).encode("ascii"))
    h.update(b"\0")
    h.update(span_signature.encode("utf-8"))
    return h.hexdigest()[:24]


def _span_signature(spans: list[Span]) -> str:
    """Stable content fingerprint over a trace's spans (order-insensitive)."""
    parts = sorted(
        f"{s.span_id}:{s.operation_name}:{s.status}:{s.duration_us}"
        for s in spans
    )
    return hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()


def _span_from_dict(d: dict[str, Any]) -> Span | None:
    trace_id = d.get("trace_id")
    span_id = d.get("span_id")
    if not trace_id or not span_id:
        return None
    start = _parse_dt(d.get("start_time"))
    if start is None:
        return None
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=d.get("parent_span_id"),
        service_name=d.get("service_name", "unknown"),
        operation_name=d.get("operation_name", ""),
        start_time=start,
        duration_us=int(d.get("duration_us") or 0),
        status=d.get("status", "OK"),
        status_message=d.get("status_message", "") or "",
        attributes=dict(d.get("attributes") or {}),
        events=list(d.get("events") or []),
    )


def _log_from_dict(d: dict[str, Any]) -> LogEntry | None:
    ts = _parse_dt(d.get("timestamp"))
    if ts is None:
        return None
    return LogEntry(
        timestamp=ts,
        service_name=d.get("service_name", "unknown"),
        level=d.get("level", "INFO"),
        message=d.get("message", ""),
        trace_id=d.get("trace_id"),
        fields=dict(d.get("fields") or {}),
    )


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _earliest(spans: list[Span]) -> datetime:
    return min(s.start_time for s in spans)
