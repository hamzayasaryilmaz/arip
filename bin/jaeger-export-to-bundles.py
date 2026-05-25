#!/usr/bin/env python3
"""Convert Jaeger JSON export → JSONL trace bundles for `arip observe`.

Operator workflow:

    # 1. Export traces from Jaeger UI (or `curl /api/traces?...`)
    # 2. Convert to trace bundles
    python3 bin/jaeger-export-to-bundles.py \\
        --in jaeger-export.json \\
        --out /tmp/bundles.jsonl
    # 3. Observe
    uv run arip observe /tmp/bundles.jsonl

This is operator tooling, deliberately NOT part of `arip_core`. The
observation module stays untouched; this script just shapes external
exports into the JSONL trace-bundle format that JsonlTraceSource
already accepts.

Accepts either:
  - Jaeger's full search response: { "data": [ {trace}, {trace}, ... ] }
  - A single trace response:        { "data": [ {trace} ] }
  - A bare trace object:            {trace}

A "trace" follows Jaeger's native JSON wire format with `traceID`,
`spans` array, and a `processes` map for service-name lookup. The
conversion mirrors what JaegerClient._spans_from_trace already does
in code — this script just emits the result as JSON-serialisable
spans for offline ingestion.

Logs ingestion is separate (see loki-export-to-logs.py and the
INGESTION_GUIDE for how to join). This script emits trace bundles
with an empty `logs: []`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _us_to_iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc).isoformat()


def _normalize_tag_value(value: Any, type_: str | None) -> Any:
    """Jaeger tags are typed. Coerce them to plain JSON values."""
    if type_ in {"int64", "float64"}:
        try:
            return int(value) if type_ == "int64" else float(value)
        except (TypeError, ValueError):
            return value
    if type_ == "bool":
        return bool(value)
    return value


def _span_dict(raw: dict[str, Any], processes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    trace_id = raw.get("traceID")
    span_id = raw.get("spanID")
    if not trace_id or not span_id:
        return None
    process = processes.get(raw.get("processID", ""), {})
    svc = process.get("serviceName") or "unknown"

    tags: dict[str, Any] = {}
    for tag in raw.get("tags") or []:
        key = tag.get("key")
        if key:
            tags[key] = _normalize_tag_value(tag.get("value"), tag.get("type"))

    status = "OK"
    if tags.get("otel.status_code") == "ERROR" or tags.get("error") is True:
        status = "ERROR"
    status_message = (
        tags.get("otel.status_description")
        or tags.get("error.message")
        or ""
    )

    parent = None
    for ref in raw.get("references") or []:
        if ref.get("refType") == "CHILD_OF":
            parent = ref.get("spanID")

    events: list[dict[str, Any]] = []
    for ev in raw.get("logs") or []:
        ts = ev.get("timestamp")
        if ts is None:
            continue
        fields = {}
        for f in ev.get("fields") or []:
            key = f.get("key")
            if key:
                fields[key] = _normalize_tag_value(f.get("value"), f.get("type"))
        events.append({"timestamp": _us_to_iso(int(ts)), "fields": fields})

    start_us = raw.get("startTime")
    duration_us = raw.get("duration") or 0
    if start_us is None:
        return None

    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent,
        "service_name": svc,
        "operation_name": raw.get("operationName") or "",
        "start_time": _us_to_iso(int(start_us)),
        "duration_us": int(duration_us),
        "status": status,
        "status_message": status_message,
        "attributes": tags,
        "events": events,
    }


def _traces_from_payload(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict) and "data" in payload:
        for t in payload.get("data") or []:
            if isinstance(t, dict):
                yield t
    elif isinstance(payload, dict) and "traceID" in payload:
        yield payload
    elif isinstance(payload, list):
        for t in payload:
            if isinstance(t, dict):
                yield t
    else:
        raise SystemExit(
            "input does not look like Jaeger JSON: expected an object "
            "with 'data', a list of traces, or a single trace object."
        )


def _bundle_from_trace(trace: dict[str, Any]) -> dict[str, Any] | None:
    trace_id = trace.get("traceID")
    if not trace_id:
        return None
    processes = trace.get("processes") or {}
    span_dicts: list[dict[str, Any]] = []
    earliest_us: int | None = None
    for raw in trace.get("spans") or []:
        sd = _span_dict(raw, processes)
        if sd is None:
            continue
        span_dicts.append(sd)
        st = raw.get("startTime")
        if isinstance(st, int) and (earliest_us is None or st < earliest_us):
            earliest_us = st
    if not span_dicts:
        return None
    captured_at = _us_to_iso(earliest_us) if earliest_us is not None else datetime.now(tz=timezone.utc).isoformat()
    return {
        "trace_id": trace_id,
        "captured_at": captured_at,
        "spans": span_dicts,
        "logs": [],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--in", dest="src", type=Path, required=True, help="Jaeger JSON export")
    p.add_argument("--out", dest="dst", type=Path, required=True, help="Output JSONL trace bundles")
    args = p.parse_args(argv)

    payload = json.loads(args.src.read_text())
    bundles: list[dict[str, Any]] = []
    for trace in _traces_from_payload(payload):
        b = _bundle_from_trace(trace)
        if b is not None:
            bundles.append(b)

    args.dst.parent.mkdir(parents=True, exist_ok=True)
    with args.dst.open("w") as fh:
        for b in bundles:
            fh.write(json.dumps(b))
            fh.write("\n")

    sys.stderr.write(
        f"converted {len(bundles)} traces from {args.src} → {args.dst}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
