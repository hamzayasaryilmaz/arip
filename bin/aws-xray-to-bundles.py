#!/usr/bin/env python3
"""Convert AWS X-Ray segments → ARIP JSONL trace bundles.

AWS X-Ray uses a proprietary "segment" format that's similar to
OTel spans but with AWS-specific structure. This adapter converts
X-Ray segments (as returned by BatchGetTraces) into ARIP's bundle
format.

Operator workflow:

  # Step 1: discover trace IDs via X-Ray GetTraceSummaries
  # (use AWS CLI to avoid pulling boto3 as a dependency)
  aws xray get-trace-summaries \\
    --start-time "$(date -u -v-1H +%s)" \\
    --end-time "$(date -u +%s)" \\
    --output json \\
    > /tmp/xray-summaries.json

  # Step 2: pull each trace's full segments
  TRACE_IDS=$(jq -r '.TraceSummaries[].Id' /tmp/xray-summaries.json | head -50)
  aws xray batch-get-traces \\
    --trace-ids $TRACE_IDS \\
    --output json \\
    > /tmp/xray-traces.json

  # Step 3: convert
  python3 bin/aws-xray-to-bundles.py \\
    --in /tmp/xray-traces.json \\
    --out /tmp/bundles.jsonl

  # Step 4: observe
  uv run arip observe /tmp/bundles.jsonl

X-Ray segment shape (after JSON unwrap from the API):
  {
    "Id": "<segment_id, hex>",          → span_id
    "TraceId": "1-<32-hex>",            → trace_id (we strip the "1-" prefix
                                          AND dashes per ARIP convention)
    "ParentId": "<segment_id>",         → parent_span_id (optional)
    "Name": "<service-name>",           → service_name + operation_name source
    "Origin": "AWS::ECS::Container",    → attribute
    "StartTime": 1234567890.123,        → start_time
    "EndTime": 1234567892.456,          → duration_us
    "Fault": true | "Error": true       → status: ERROR
    "Http": {...},                      → flattened to attributes
    "Aws": {...},                       → flattened to attributes
    "Subsegments": [...]                → recursive segments, treated as child spans
  }

Caveats (honest):
- This adapter has been tested against synthetic X-Ray fixtures.
  Real-world X-Ray data may have variations we haven't seen.
- Subsegments are flattened into individual spans. The hierarchy
  is preserved via parent_span_id. Some X-Ray-specific concepts
  (annotations vs metadata, exception subsegments) are dropped.
- X-Ray's trace ID format is "1-{32-hex}". We strip the version
  prefix to produce a standard hex trace_id.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _xray_trace_id_to_hex(xray_id: str) -> str:
    """X-Ray uses '1-<8hex>-<24hex>'. Strip version + dashes."""
    if xray_id.startswith("1-"):
        xray_id = xray_id[2:]
    return xray_id.replace("-", "")


def _epoch_to_iso(t: float | int | None) -> str | None:
    if t is None:
        return None
    try:
        return datetime.fromtimestamp(float(t), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _flatten(prefix: str, d: dict[str, Any], out: dict[str, Any]) -> None:
    """Flatten nested dict into dotted-key attributes (one level deep is enough)."""
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _flatten(key, v, out)
        elif isinstance(v, (str, int, float, bool)):
            out[key] = v


def _segment_to_span(
    segment: dict[str, Any],
    trace_id_hex: str,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Convert one X-Ray segment to an ARIP span. Subsegments are
    NOT recursed here — caller flattens via _walk_segments."""
    seg_id = segment.get("Id", "")
    name = segment.get("Name", "unknown")
    origin = segment.get("Origin", "")

    # X-Ray's "Name" is typically the service name. There's no
    # separate operation name in X-Ray's data model for top-level
    # segments. For subsegments, Name is the operation.
    service_name = name
    operation_name = name
    if origin and ":" in origin:
        # e.g. "AWS::Lambda::Function" → operation could include this
        operation_name = f"{name} ({origin})"

    # Status: X-Ray uses Error, Fault, Throttle booleans
    is_error = bool(
        segment.get("Error") or segment.get("Fault") or segment.get("Throttle")
    )
    status_str = "ERROR" if is_error else "OK"
    status_msg = ""
    if "Cause" in segment:
        cause = segment["Cause"]
        if isinstance(cause, dict):
            exceptions = cause.get("Exceptions") or []
            if exceptions:
                status_msg = exceptions[0].get("Message", "")
        elif isinstance(cause, str):
            status_msg = cause

    # Attributes: flatten Http, Aws, User, etc.
    attributes: dict[str, Any] = {}
    for section_key in ("Http", "Aws", "User", "Annotations", "Metadata"):
        section = segment.get(section_key)
        if isinstance(section, dict):
            _flatten(section_key.lower(), section, attributes)
    if origin:
        attributes["aws.origin"] = origin

    start_iso = _epoch_to_iso(segment.get("StartTime"))
    end_t = segment.get("EndTime")
    duration_us = 0
    if start_iso and end_t is not None:
        try:
            duration_us = max(
                0,
                int((float(end_t) - float(segment.get("StartTime", 0))) * 1_000_000),
            )
        except (TypeError, ValueError):
            duration_us = 0

    return {
        "trace_id": trace_id_hex,
        "span_id": seg_id,
        "parent_span_id": parent_id,
        "service_name": service_name,
        "operation_name": operation_name,
        "start_time": start_iso or _epoch_to_iso(0) or "1970-01-01T00:00:00+00:00",
        "duration_us": duration_us,
        "status": status_str,
        "status_message": status_msg,
        "attributes": attributes,
        "events": [],
    }


def _walk_segments(
    segment: dict[str, Any],
    trace_id_hex: str,
    parent_id: str | None,
    out: list[dict[str, Any]],
) -> None:
    """Recursively walk a segment + subsegments, emitting one span per node."""
    span = _segment_to_span(segment, trace_id_hex, parent_id)
    out.append(span)
    for sub in segment.get("Subsegments") or []:
        _walk_segments(sub, trace_id_hex, span["span_id"], out)


def _hits_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """X-Ray batch-get-traces returns:
    {
      "Traces": [
        {"Id": "1-<...>", "Duration": ..., "Segments": [{"Id": ..., "Document": "<json-string>"}, ...]},
        ...
      ],
      "UnprocessedTraceIds": [...]
    }

    Note: the segment Document is a JSON-encoded STRING, not nested JSON!
    """
    text = path.read_text()
    if not text.strip():
        return
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        sys.stderr.write("ERROR: could not parse X-Ray export as JSON\n")
        return

    traces = payload.get("Traces") or []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        trace_id_raw = trace.get("Id", "")
        trace_id_hex = _xray_trace_id_to_hex(trace_id_raw)
        if not trace_id_hex:
            continue
        # Each Segment has a Document field with a JSON-string payload
        for seg_wrapper in trace.get("Segments") or []:
            doc_str = seg_wrapper.get("Document", "")
            if not doc_str:
                continue
            try:
                segment = json.loads(doc_str)
            except json.JSONDecodeError:
                continue
            yield (trace_id_hex, segment)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--in", dest="src_file", type=Path, required=True,
        help="AWS X-Ray batch-get-traces JSON output",
    )
    p.add_argument(
        "--out", type=Path, required=True,
        help="Output JSONL trace bundles",
    )
    args = p.parse_args(argv)

    spans_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    earliest_by_trace: dict[str, str] = {}
    total_segments = 0

    for trace_id_hex, segment in _hits_from_file(args.src_file):
        spans_acc: list[dict[str, Any]] = []
        _walk_segments(segment, trace_id_hex, parent_id=None, out=spans_acc)
        for span in spans_acc:
            spans_by_trace[trace_id_hex].append(span)
            total_segments += 1
            ts = span["start_time"]
            if (
                trace_id_hex not in earliest_by_trace
                or ts < earliest_by_trace[trace_id_hex]
            ):
                earliest_by_trace[trace_id_hex] = ts

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
        f"wrote {written} trace bundle(s) ({total_segments} spans from "
        f"X-Ray segments/subsegments) → {args.out}\n"
    )
    if written == 0:
        sys.stderr.write(
            "WARNING: zero bundles written. Likely causes:\n"
            "  - Input is not an X-Ray batch-get-traces response\n"
            "  - All traces had empty Segments\n"
            "  - Segment Documents failed JSON parsing\n"
            "Verify with: jq '.Traces[0] | {Id, segment_count: (.Segments | length)}' INPUT\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
