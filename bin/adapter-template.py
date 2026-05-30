#!/usr/bin/env python3
"""TEMPLATE — Convert <VENDOR> spans → ARIP JSONL trace bundles.

Copy this file to bin/<vendor>-export-to-bundles.py and adapt.
Search for `<VENDOR>` and `<TODO>` markers; fill them in.

See docs/WRITING_AN_ADAPTER.md for the full walkthrough.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ─── Default field paths ─────────────────────────────────────────
# These map common <VENDOR> field names to what ARIP needs. Operators
# can override via CLI flags. Order matters: first-found wins.

DEFAULT_TRACE_ID_FIELDS = ["trace_id", "trace.id", "traceID"]
DEFAULT_SPAN_ID_FIELDS = ["span_id", "span.id", "spanID"]
DEFAULT_PARENT_FIELDS = ["parent_span_id", "parent.id", "parentSpanID"]
DEFAULT_SERVICE_FIELDS = ["service.name", "service_name"]
DEFAULT_OPERATION_FIELDS = ["name", "operation_name", "span.name"]
DEFAULT_TIMESTAMP_FIELDS = ["@timestamp", "timestamp", "start_time"]
DEFAULT_DURATION_FIELDS = ["duration_us", "duration"]
DEFAULT_STATUS_FIELDS = ["status.code", "otel.status_code", "status"]


def _dig(doc: dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted path through nested dicts.
    Handles both flat (`service.name` as literal key) and nested
    (`service: {name: ...}`) representations."""
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
    """Normalize timestamps (string ISO, epoch_ms, epoch_us, epoch_ns)."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        # Heuristic: > 1e15 = ns, > 1e12 = ms, else s
        if v > 1e15:
            return datetime.fromtimestamp(v / 1e9, tz=timezone.utc).isoformat()
        if v > 1e12:
            return datetime.fromtimestamp(v / 1e3, tz=timezone.utc).isoformat()
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
    return None


def _duration_us(v: Any) -> int:
    """Coerce duration to microseconds."""
    if v is None:
        return 0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    if n > 1e9:        # nanos
        return int(n / 1000)
    if n > 1e6:        # already micros
        return int(n)
    return int(n * 1000)  # millis


def _status(v: Any) -> tuple[str, str]:
    """Normalize status to (status_str, status_msg)."""
    if v is None:
        return ("OK", "")
    if isinstance(v, str):
        return ("ERROR", "") if v.upper() in ("ERROR", "STATUS_CODE_ERROR") else ("OK", "")
    if isinstance(v, int):
        return ("ERROR", "") if v == 2 else ("OK", "")
    if isinstance(v, dict):
        code = v.get("code")
        msg = v.get("message", "") or ""
        return ("ERROR", msg) if code in (2, "ERROR", "STATUS_CODE_ERROR") else ("OK", msg)
    return ("OK", "")


class _FieldConfig:
    def __init__(self, args: argparse.Namespace) -> None:
        self.trace_id = [args.trace_id_field] if args.trace_id_field else DEFAULT_TRACE_ID_FIELDS
        self.span_id = [args.span_id_field] if args.span_id_field else DEFAULT_SPAN_ID_FIELDS
        self.parent = [args.parent_field] if args.parent_field else DEFAULT_PARENT_FIELDS
        self.service = [args.service_field] if args.service_field else DEFAULT_SERVICE_FIELDS
        self.operation = [args.operation_field] if args.operation_field else DEFAULT_OPERATION_FIELDS
        self.timestamp = [args.timestamp_field] if args.timestamp_field else DEFAULT_TIMESTAMP_FIELDS
        self.duration = [args.duration_field] if args.duration_field else DEFAULT_DURATION_FIELDS
        self.status = [args.status_field] if args.status_field else DEFAULT_STATUS_FIELDS


def _span_from_doc(doc: dict[str, Any], cfg: _FieldConfig) -> dict[str, Any] | None:
    """Convert one backend span document to ARIP-bundle span dict.

    <TODO>: customize if your backend needs:
    - Special ID decoding (base64, integer, etc.)
    - Vendor-specific attribute unwrapping
    - Status code mapping that doesn't fit the standard cases above
    """
    trace_id = _first(doc, cfg.trace_id)
    span_id = _first(doc, cfg.span_id)
    if not trace_id or not span_id:
        return None
    start_iso = _to_iso(_first(doc, cfg.timestamp))
    if not start_iso:
        return None

    parent = _first(doc, cfg.parent)
    service = _first(doc, cfg.service) or "unknown"
    operation = _first(doc, cfg.operation) or ""
    duration = _duration_us(_first(doc, cfg.duration))
    status_str, status_msg = _status(_first(doc, cfg.status))

    # Best-effort attribute extraction: anything not already extracted
    attributes: dict[str, Any] = {}
    consumed = set(
        cfg.trace_id + cfg.span_id + cfg.parent + cfg.service
        + cfg.operation + cfg.timestamp + cfg.duration + cfg.status
        + ["_index", "_id", "_score", "_source"]
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


def _hits_from_vendor(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    """Live query path. Implement based on the backend's API.

    <TODO>: replace this skeleton with the actual API call. Pattern:
    - Authenticate via args.api_key / args.basic_auth / etc.
    - Page through results (search_after / next_token / offset)
    - Yield each span document
    - Respect args.max_hits as upper bound
    """
    import httpx

    headers: dict[str, str] = {}
    # <TODO>: set auth header
    # e.g., headers["Authorization"] = f"Bearer {args.api_key}"

    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        # <TODO>: replace with actual endpoint + query
        # response = client.get(f"{args.vendor_url}/spans", headers=headers, params={...})
        # response.raise_for_status()
        # for doc in response.json().get("data", []):
        #     yield doc
        raise NotImplementedError("Implement live <VENDOR> query path")


def _hits_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """File path can be:
    - JSON: { "hits": { "hits": [...] } } (raw response)
    - JSON: { "data": [...] }  (alternative wrapper)
    - JSON: [ {doc}, ... ]     (array of source docs)
    - NDJSON: one doc per line
    """
    text = path.read_text()
    stripped = text.strip()
    if not stripped:
        return

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            # <TODO>: adjust based on vendor's response shape
            for wrapper_key in ("hits.hits", "data", "spans"):
                cur: Any = payload
                for part in wrapper_key.split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                if isinstance(cur, list):
                    for h in cur:
                        if isinstance(h, dict):
                            yield h.get("_source") or h
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
                        yield d.get("_source") or d
                return
        except json.JSONDecodeError:
            pass

    # NDJSON fallback
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            yield d.get("_source") or d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--in", dest="src_file", type=Path,
                     help="Pre-pulled span dump (JSON/NDJSON)")
    src.add_argument("--vendor-url",
                     help="Live <VENDOR> URL (e.g. https://api.vendor.com)")

    # <TODO>: add vendor-specific auth args
    # p.add_argument("--api-key", help="<VENDOR> API key")
    # p.add_argument("--query", help="<VENDOR> query")
    p.add_argument("--insecure", action="store_true", help="Skip TLS verification")
    p.add_argument("--max-hits", type=int, default=5000,
                   help="Cap total spans pulled (default 5000)")

    p.add_argument("--out", type=Path, required=True,
                   help="Output JSONL trace bundles")

    # Field overrides
    p.add_argument("--trace-id-field", help=f"Default: {DEFAULT_TRACE_ID_FIELDS}")
    p.add_argument("--span-id-field", help=f"Default: {DEFAULT_SPAN_ID_FIELDS}")
    p.add_argument("--parent-field", help=f"Default: {DEFAULT_PARENT_FIELDS}")
    p.add_argument("--service-field", help=f"Default: {DEFAULT_SERVICE_FIELDS}")
    p.add_argument("--operation-field", help=f"Default: {DEFAULT_OPERATION_FIELDS}")
    p.add_argument("--timestamp-field", help=f"Default: {DEFAULT_TIMESTAMP_FIELDS}")
    p.add_argument("--duration-field", help=f"Default: {DEFAULT_DURATION_FIELDS}")
    p.add_argument("--status-field", help=f"Default: {DEFAULT_STATUS_FIELDS}")

    args = p.parse_args(argv)
    cfg = _FieldConfig(args)
    docs = _hits_from_vendor(args) if args.vendor_url else _hits_from_file(args.src_file)

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
        f"wrote {written} trace bundle(s) "
        f"({sum(len(s) for s in spans_by_trace.values())} spans), "
        f"skipped {skipped} unparseable doc(s) → {args.out}\n"
    )
    if skipped > 0 and written == 0:
        sys.stderr.write(
            "WARNING: zero bundles written but docs were present. "
            "Likely field-mapping mismatch — check your schema and pass "
            "--*-field overrides to point at the right fields.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
