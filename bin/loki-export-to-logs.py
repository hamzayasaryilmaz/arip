#!/usr/bin/env python3
"""Convert Loki query response → log entries joined onto existing trace bundles.

Operator workflow:

    # 1. Export logs from Loki (`logcli query '{service="..."}' --output=json`)
    # 2. Either: emit logs as a standalone JSON dict for joining later,
    #    or join them into existing JSONL bundles in place.
    python3 bin/loki-export-to-logs.py \\
        --in loki-export.json \\
        --bundles /tmp/bundles.jsonl \\
        --out   /tmp/bundles-with-logs.jsonl

The join is by `trace_id`: each Loki log entry is parsed for a
`trace_id` value (looked up in the stream labels first, then in the
log line body via a configurable JSON field), and dropped into the
matching bundle's `logs` list. Log entries with no resolvable
trace_id are written to a side-by-side file (`--unmatched-out`) so
the operator can see what fell on the floor.

This is operator tooling, deliberately NOT part of `arip_core`. It
exists only to bridge external exports into the JSONL trace-bundle
format that JsonlTraceSource already accepts.

Supports Loki's standard JSON response shape:

    {
      "status": "success",
      "data": {
        "resultType": "streams",
        "result": [
          {
            "stream": {"service_name": "...", "level": "..."},
            "values": [["<ns-timestamp>", "<log line>"], ...]
          }
        ]
      }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _ns_to_iso(ns_str: str) -> str:
    try:
        ns = int(ns_str)
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc).isoformat()
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()


_TRACE_KEY_FALLBACKS = ("trace_id", "traceID", "traceid", "trace.id", "otelTraceID")


def _resolve_trace_id(line: str, stream_labels: dict[str, Any], trace_key: str) -> str | None:
    """Resolve a trace_id from the stream labels or from a JSON line body.

    Tries the operator-specified key first, then a fallback chain that
    covers every variant we've seen in real Loki exports:
      - `trace_id` (Loki label convention)
      - `traceID` (Tempo / Jaeger style)
      - `traceid` (OTel Python SDK Loki exporter — lowercase, no underscore)
      - `trace.id` (dotted style)
      - `otelTraceID` (OTel auto-instrumentation attribute key)
    """
    candidates = [trace_key, *(k for k in _TRACE_KEY_FALLBACKS if k != trace_key)]
    for k in candidates:
        v = stream_labels.get(k)
        if v:
            return str(v)
    line = (line or "").strip()
    if not line or not (line.startswith("{") and line.endswith("}")):
        return None
    try:
        body = json.loads(line)
    except json.JSONDecodeError:
        return None
    # Body may also have an `attributes` sub-dict (OTel Python emits there).
    attrs = body.get("attributes") if isinstance(body.get("attributes"), dict) else {}
    for k in candidates:
        v = body.get(k) or attrs.get(k)
        if v:
            return str(v)
    return None


def _logs_from_loki(payload: dict[str, Any], trace_key: str = "trace_id") -> Iterable[dict[str, Any]]:
    data = payload.get("data") or {}
    result = data.get("result") or []
    for stream in result:
        labels = stream.get("stream") or {}
        # `job` is what the OTel-Collector loki exporter sets by default
        # (it maps to OTEL_SERVICE_NAME). `service.name` is OTel's
        # canonical attribute. Try all common spellings.
        svc = (
            labels.get("service_name")
            or labels.get("service.name")
            or labels.get("service")
            or labels.get("job")
            or labels.get("app")
            or "unknown"
        )
        level = (labels.get("level") or "INFO").upper()
        for entry in stream.get("values") or []:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            ts_ns, line = entry[0], entry[1]
            tid = _resolve_trace_id(line, labels, trace_key)
            yield {
                "timestamp": _ns_to_iso(ts_ns),
                "service_name": svc,
                "level": level,
                "message": line,
                "trace_id": tid,
                "fields": dict(labels),
            }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--in", dest="src", type=Path, required=True, help="Loki JSON export")
    p.add_argument("--bundles", type=Path, required=True, help="Existing JSONL trace bundles to join into")
    p.add_argument("--out", type=Path, required=True, help="Output JSONL bundles with joined logs")
    p.add_argument("--unmatched-out", type=Path, default=None, help="Write unmatched logs (no trace_id) here")
    p.add_argument("--trace-key", default="trace_id", help="Field/label name for trace_id (default: trace_id)")
    args = p.parse_args(argv)

    payload = json.loads(args.src.read_text())
    logs_by_trace: dict[str, list[dict[str, Any]]] = {}
    unmatched: list[dict[str, Any]] = []
    for log in _logs_from_loki(payload, trace_key=args.trace_key):
        tid = log.get("trace_id")
        if tid:
            logs_by_trace.setdefault(tid, []).append(log)
        else:
            unmatched.append(log)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joined = 0
    bundles_seen = 0
    with args.bundles.open() as src, args.out.open("w") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            bundles_seen += 1
            try:
                bundle = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = bundle.get("trace_id")
            extra = logs_by_trace.get(tid) if tid else None
            if extra:
                existing = bundle.get("logs") or []
                bundle["logs"] = list(existing) + extra
                joined += len(extra)
            dst.write(json.dumps(bundle))
            dst.write("\n")

    if args.unmatched_out and unmatched:
        args.unmatched_out.parent.mkdir(parents=True, exist_ok=True)
        with args.unmatched_out.open("w") as fh:
            for log in unmatched:
                fh.write(json.dumps(log))
                fh.write("\n")

    sys.stderr.write(
        f"joined {joined} log line(s) into {bundles_seen} bundle(s); "
        f"unmatched logs: {len(unmatched)}"
        + (f" → {args.unmatched_out}" if args.unmatched_out else "")
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
