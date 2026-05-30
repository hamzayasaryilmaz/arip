#!/usr/bin/env python3
"""Convert Tempo (OTLP JSON) trace export → JSONL trace bundles for `arip observe`.

Tempo's `/api/traces/<trace_id>` endpoint returns OpenTelemetry's
protobuf-derived JSON format — `batches` containing `resource` and
`scopeSpans`, with `traceId`/`spanId` as base64 bytes, timestamps
as `*UnixNano` strings, and attribute values as typed wrapper
objects (`stringValue`/`intValue`/`boolValue`/...).

This is structurally different from Jaeger's API (which uses
`data`/`processes`/typed-tags JSON). The Jaeger adapter does NOT
work against Tempo — verified during op003 validation.

Operator workflow:

    # 1. Discover trace IDs to fetch
    curl 'http://localhost:3200/api/search?tags=&limit=100' \\
      | jq -r '.traces[].traceID' > /tmp/trace-ids.txt

    # 2. Fetch each trace into one JSON-per-line file
    while read tid; do
      curl -sf "http://localhost:3200/api/traces/$tid"
      echo
    done < /tmp/trace-ids.txt > /tmp/tempo-raw.jsonl

    # 3. Convert to ARIP trace bundles
    python3 bin/tempo-export-to-bundles.py \\
      --in /tmp/tempo-raw.jsonl \\
      --out /tmp/bundles.jsonl

    # 4. Observe
    uv run arip observe /tmp/bundles.jsonl

This is operator tooling — NOT part of `arip_core`. The observation
module is unchanged; this script just adapts Tempo's wire format to
the JSONL trace-bundle format that JsonlTraceSource already accepts.

Limitations (honest):
  - Does NOT yet support span events ("logs") inside Tempo spans
    (they're decoded as empty events list).
  - Does NOT yet fetch logs (Tempo doesn't carry logs; use a Loki
    adapter for that).
  - Does NOT support Tempo's single-trace `application/protobuf`
    response — only the JSON variant.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _b64_to_hex(s: str) -> str:
    try:
        return base64.b64decode(s).hex()
    except Exception:
        return s  # already hex, or malformed — pass through


def _ns_to_iso(ns_str: str) -> str:
    try:
        ns = int(ns_str)
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc).isoformat()
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()


def _attr_value(v: dict[str, Any]) -> Any:
    """Unwrap OTLP attribute value wrapper to plain JSON."""
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            val = v[k]
            if k == "intValue":
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return val
            if k == "doubleValue":
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return val
            return val
    if "arrayValue" in v:
        return [_attr_value(x) for x in (v["arrayValue"].get("values") or [])]
    return v


def _attrs_to_dict(attrs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in attrs or []:
        key = a.get("key")
        if key:
            out[key] = _attr_value(a.get("value", {}))
    return out


def _status_to_strings(status: dict[str, Any] | None) -> tuple[str, str]:
    if not status:
        return "OK", ""
    code = status.get("code")
    msg = status.get("message", "") or ""
    # OTLP status codes: 0=UNSET, 1=OK, 2=ERROR.
    # Numeric or string both seen in the wild.
    if code in (2, "STATUS_CODE_ERROR", "ERROR"):
        return "ERROR", msg
    return "OK", msg


def _span_dict(
    raw: dict[str, Any], service_name: str
) -> dict[str, Any] | None:
    trace_id = _b64_to_hex(raw.get("traceId", ""))
    span_id = _b64_to_hex(raw.get("spanId", ""))
    if not trace_id or not span_id:
        return None
    parent = raw.get("parentSpanId")
    parent_hex = _b64_to_hex(parent) if parent else None
    if parent_hex == "":
        parent_hex = None
    start_ns = raw.get("startTimeUnixNano")
    end_ns = raw.get("endTimeUnixNano")
    if start_ns is None:
        return None
    try:
        duration_us = max(0, (int(end_ns) - int(start_ns)) // 1000) if end_ns else 0
    except (TypeError, ValueError):
        duration_us = 0
    status_str, status_msg = _status_to_strings(raw.get("status"))
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_hex,
        "service_name": service_name,
        "operation_name": raw.get("name") or "",
        "start_time": _ns_to_iso(start_ns),
        "duration_us": int(duration_us),
        "status": status_str,
        "status_message": status_msg,
        "attributes": _attrs_to_dict(raw.get("attributes") or []),
        "events": [],
    }


def _bundle_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    batches = payload.get("batches") or []
    if not batches:
        return None
    all_spans: list[dict[str, Any]] = []
    trace_id_hex: str | None = None
    earliest_iso: str | None = None
    for batch in batches:
        resource_attrs = _attrs_to_dict(
            (batch.get("resource") or {}).get("attributes") or []
        )
        service_name = (
            resource_attrs.get("service.name")
            or resource_attrs.get("service_name")
            or "unknown"
        )
        for scope_span in batch.get("scopeSpans") or []:
            for raw in scope_span.get("spans") or []:
                sd = _span_dict(raw, str(service_name))
                if sd is None:
                    continue
                all_spans.append(sd)
                if trace_id_hex is None:
                    trace_id_hex = sd["trace_id"]
                if earliest_iso is None or sd["start_time"] < earliest_iso:
                    earliest_iso = sd["start_time"]
    if not all_spans or trace_id_hex is None:
        return None
    return {
        "trace_id": trace_id_hex,
        "captured_at": earliest_iso or datetime.now(tz=timezone.utc).isoformat(),
        "spans": all_spans,
        "logs": [],
    }


def _payloads_from_source(src: Path) -> Iterable[dict[str, Any]]:
    """Accept either: one JSON file per trace (`.json`), or JSONL with
    one trace per line (`.jsonl`)."""
    text = src.read_text()
    text_stripped = text.strip()
    if not text_stripped:
        return
    # Single JSON object?
    if text_stripped.startswith("{") and text_stripped.count("\n{") == 0:
        try:
            payload = json.loads(text_stripped)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict) and "batches" in payload:
            yield payload
        return
    # JSONL — one trace per line.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "batches" in payload:
            yield payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--in", dest="src", type=Path, required=True,
                   help="Tempo OTLP JSON (single file or JSONL of trace responses)")
    p.add_argument("--out", dest="dst", type=Path, required=True,
                   help="Output JSONL trace bundles")
    args = p.parse_args(argv)

    bundles = []
    for payload in _payloads_from_source(args.src):
        b = _bundle_from_payload(payload)
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
