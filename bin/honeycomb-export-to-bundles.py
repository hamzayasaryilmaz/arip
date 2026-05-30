#!/usr/bin/env python3
"""Convert Honeycomb spans → ARIP JSONL trace bundles.

Honeycomb is OTel-compatible — events stored are basically OTLP
spans with a slightly different naming convention. The Query API
returns events as JSON; this adapter converts them to ARIP's
bundle format.

Operator workflow:

  # Pull spans via Honeycomb's Query API (requires API key with
  # query permissions for the target dataset).
  curl -H "X-Honeycomb-Team: $HONEYCOMB_API_KEY" \\
    "https://api.honeycomb.io/1/query_results/$DATASET/$RESULT_ID" \\
    > /tmp/honeycomb-export.json

  # Convert
  python3 bin/honeycomb-export-to-bundles.py \\
    --in /tmp/honeycomb-export.json \\
    --out /tmp/bundles.jsonl

  # Or live query (creates + polls a Honeycomb query):
  python3 bin/honeycomb-export-to-bundles.py \\
    --honeycomb-api-key $HONEYCOMB_API_KEY \\
    --dataset $DATASET \\
    --time-range-minutes 60 \\
    --out /tmp/bundles.jsonl

  # Observe
  uv run arip observe /tmp/bundles.jsonl

Honeycomb event field conventions (defaults; configurable):
  trace.trace_id   → trace_id
  trace.span_id    → span_id
  trace.parent_id  → parent_span_id
  service.name     → service_name
  name             → operation_name
  duration_ms      → converted to duration_us
  status_code      → status (OK/ERROR)
  timestamp        → start_time
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_TRACE_ID_FIELDS = ["trace.trace_id", "trace_id"]
DEFAULT_SPAN_ID_FIELDS = ["trace.span_id", "span_id"]
DEFAULT_PARENT_FIELDS = ["trace.parent_id", "parent_span_id"]
DEFAULT_SERVICE_FIELDS = ["service.name", "service_name", "app.service"]
DEFAULT_OPERATION_FIELDS = ["name", "operation.name"]
DEFAULT_TIMESTAMP_FIELDS = ["timestamp", "time", "@timestamp"]
DEFAULT_DURATION_FIELDS = ["duration_ms", "duration_us"]
DEFAULT_STATUS_FIELDS = ["status_code", "error", "otel.status_code"]


def _dig(doc: dict[str, Any], dotted: str) -> Any:
    if dotted in doc:
        return doc[dotted]
    cur: Any = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _first(doc: dict[str, Any], fields: list[str]) -> Any:
    for f in fields:
        v = _dig(doc, f)
        if v is not None:
            return v
    return None


def _to_iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return (
                datetime.fromisoformat(v.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .isoformat()
            )
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        if v > 1e15:
            return datetime.fromtimestamp(v / 1e9, tz=timezone.utc).isoformat()
        if v > 1e12:
            return datetime.fromtimestamp(v / 1e3, tz=timezone.utc).isoformat()
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
    return None


def _duration_us(v: Any, field_name: str) -> int:
    """Honeycomb uses duration_ms by default; some pipelines use _us.
    Use the field NAME to decide rather than guessing from magnitude."""
    if v is None:
        return 0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    if field_name.endswith("_us"):
        return int(n)
    if field_name.endswith("_ns"):
        return int(n / 1000)
    # Default: assume ms
    return int(n * 1000)


def _status(doc: dict[str, Any], cfg) -> tuple[str, str]:
    """Honeycomb has multiple status conventions:
    - `error: true` boolean
    - `status_code: ERROR` string
    - `otel.status_code: 2` numeric"""
    for f in cfg.status:
        v = _dig(doc, f)
        if v is None:
            continue
        if isinstance(v, bool):
            return ("ERROR", "") if v else ("OK", "")
        if isinstance(v, str):
            if v.upper() in ("ERROR", "STATUS_CODE_ERROR"):
                return ("ERROR", str(doc.get("status_message", "") or ""))
            return ("OK", "")
        if isinstance(v, int):
            return ("ERROR", "") if v == 2 else ("OK", "")
    return ("OK", "")


class _Cfg:
    def __init__(self, args: argparse.Namespace) -> None:
        self.trace_id = [args.trace_id_field] if args.trace_id_field else DEFAULT_TRACE_ID_FIELDS
        self.span_id = [args.span_id_field] if args.span_id_field else DEFAULT_SPAN_ID_FIELDS
        self.parent = [args.parent_field] if args.parent_field else DEFAULT_PARENT_FIELDS
        self.service = [args.service_field] if args.service_field else DEFAULT_SERVICE_FIELDS
        self.operation = [args.operation_field] if args.operation_field else DEFAULT_OPERATION_FIELDS
        self.timestamp = [args.timestamp_field] if args.timestamp_field else DEFAULT_TIMESTAMP_FIELDS
        self.duration = [args.duration_field] if args.duration_field else DEFAULT_DURATION_FIELDS
        self.status = [args.status_field] if args.status_field else DEFAULT_STATUS_FIELDS


def _span_from_doc(doc: dict[str, Any], cfg: _Cfg) -> dict[str, Any] | None:
    trace_id = _first(doc, cfg.trace_id)
    span_id = _first(doc, cfg.span_id)
    if not trace_id or not span_id:
        return None
    start_iso = _to_iso(_first(doc, cfg.timestamp))
    if not start_iso:
        return None

    # Find which duration field was used (for unit detection)
    duration_field = ""
    duration_val: Any = None
    for f in cfg.duration:
        v = _dig(doc, f)
        if v is not None:
            duration_field = f
            duration_val = v
            break

    parent = _first(doc, cfg.parent)
    service = _first(doc, cfg.service) or "unknown"
    operation = _first(doc, cfg.operation) or ""
    duration = _duration_us(duration_val, duration_field)
    status_str, status_msg = _status(doc, cfg)

    attributes: dict[str, Any] = {}
    consumed = set(
        cfg.trace_id + cfg.span_id + cfg.parent + cfg.service
        + cfg.operation + cfg.timestamp + cfg.duration + cfg.status
    )
    for k, v in doc.items():
        if k in consumed:
            continue
        if isinstance(v, (str, int, float, bool)):
            attributes[k] = v

    return {
        "trace_id": str(trace_id),
        "span_id": str(span_id),
        "parent_span_id": str(parent) if parent else None,
        "service_name": str(service),
        "operation_name": str(operation),
        "start_time": start_iso,
        "duration_us": duration,
        "status": status_str,
        "status_message": status_msg,
        "attributes": attributes,
        "events": [],
    }


def _hits_from_honeycomb(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    """Live query path: create a query, poll for results, page through."""
    import httpx

    api = f"https://api.honeycomb.io/1"
    headers = {
        "X-Honeycomb-Team": args.honeycomb_api_key,
        "Content-Type": "application/json",
    }
    # Create the query
    query_body = {
        "calculations": [{"op": "COUNT"}],
        "time_range": args.time_range_minutes * 60,
        "granularity": 0,
        "limit": min(args.max_hits, 10000),
    }
    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        # Create query
        resp = client.post(
            f"{api}/queries/{args.dataset}",
            headers=headers,
            json=query_body,
        )
        resp.raise_for_status()
        query_id = resp.json()["id"]

        # Run query
        resp = client.post(
            f"{api}/query_results/{args.dataset}",
            headers=headers,
            json={"query_id": query_id, "disable_series": False},
        )
        resp.raise_for_status()
        result_id = resp.json()["id"]

        # Poll for completion (Honeycomb queries are async)
        for _ in range(60):  # max 60 * 2s = 2 min
            time.sleep(2)
            resp = client.get(
                f"{api}/query_results/{args.dataset}/{result_id}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("complete"):
                events = data.get("data", {}).get("results", [])
                for e in events:
                    yield e
                return
        raise TimeoutError("Honeycomb query did not complete within 2 minutes")


def _hits_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """JSON or NDJSON. Honeycomb query_results have `.data.results: [...]`."""
    text = path.read_text()
    stripped = text.strip()
    if not stripped:
        return

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            # Honeycomb's query_results shape
            results = (payload.get("data") or {}).get("results")
            if isinstance(results, list):
                for r in results:
                    yield r
                return
            # Generic wrappers
            for key in ("results", "data", "events"):
                v = payload.get(key) if isinstance(payload, dict) else None
                if isinstance(v, list):
                    for d in v:
                        if isinstance(d, dict):
                            yield d
                    return
            if isinstance(payload, dict):
                yield payload
                return
        except json.JSONDecodeError:
            pass

    if stripped.startswith("["):
        try:
            arr = json.loads(stripped)
            if isinstance(arr, list):
                for d in arr:
                    if isinstance(d, dict):
                        yield d
                return
        except json.JSONDecodeError:
            pass

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            yield d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--in", dest="src_file", type=Path,
                     help="Pre-pulled Honeycomb export (JSON/NDJSON)")
    src.add_argument("--honeycomb-api-key",
                     help="Honeycomb API key with query permissions")

    p.add_argument("--dataset", help="Honeycomb dataset name (required with --honeycomb-api-key)")
    p.add_argument("--time-range-minutes", type=int, default=60,
                   help="Query window (default: 60 minutes)")
    p.add_argument("--max-hits", type=int, default=5000)
    p.add_argument("--insecure", action="store_true")

    p.add_argument("--out", type=Path, required=True)

    p.add_argument("--trace-id-field")
    p.add_argument("--span-id-field")
    p.add_argument("--parent-field")
    p.add_argument("--service-field")
    p.add_argument("--operation-field")
    p.add_argument("--timestamp-field")
    p.add_argument("--duration-field")
    p.add_argument("--status-field")

    args = p.parse_args(argv)
    if args.honeycomb_api_key and not args.dataset:
        p.error("--honeycomb-api-key requires --dataset")

    cfg = _Cfg(args)
    docs = _hits_from_honeycomb(args) if args.honeycomb_api_key else _hits_from_file(args.src_file)

    spans_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    earliest_by_trace: dict[str, str] = {}
    skipped = 0
    for doc in docs:
        span = _span_from_doc(doc, cfg)
        if span is None:
            skipped += 1
            continue
        tid = span["trace_id"]
        spans_by_trace[tid].append(span)
        ts = span["start_time"]
        if tid not in earliest_by_trace or ts < earliest_by_trace[tid]:
            earliest_by_trace[tid] = ts

    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.out.open("w") as fh:
        for tid, spans in spans_by_trace.items():
            bundle = {
                "trace_id": tid,
                "captured_at": earliest_by_trace[tid],
                "spans": spans,
                "logs": [],
            }
            fh.write(json.dumps(bundle))
            fh.write("\n")
            written += 1

    sys.stderr.write(
        f"wrote {written} Honeycomb trace bundle(s) "
        f"({sum(len(s) for s in spans_by_trace.values())} spans), "
        f"skipped {skipped} → {args.out}\n"
    )
    if skipped > 0 and written == 0:
        sys.stderr.write(
            "WARNING: zero bundles written but events were present. "
            "Likely field-mapping mismatch — Honeycomb's field names "
            "vary by SDK. Check your event schema and pass --*-field overrides.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
