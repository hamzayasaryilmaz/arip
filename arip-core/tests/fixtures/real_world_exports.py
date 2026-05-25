"""Fixtures for real-world telemetry export shapes.

These emulate the wire formats engineers actually have to ingest from:
Jaeger's HTTP API, Loki's query response, GHA artifact archives. They
are NOT a substitute for real pilot telemetry — they are the closest
honest synthetic stand-in.

Pathologies baked in (each one observed in real exports in the wild):
  - typed Jaeger tags (int64, bool) with explicit `type` field
  - operationName with embedded path parameters
  - mixed services in one trace
  - Loki stream labels that DO carry trace_id vs ones that DON'T
  - Loki log lines that are JSON bodies vs free text
  - nanosecond timestamps
  - sampled trace with orphan span (parent in another sampled batch)
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


T0_US = int(datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)
T0_NS = T0_US * 1_000


# ---------- Jaeger native JSON shape -------------------------------


def _jaeger_tag(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "type": "bool", "value": value}
    if isinstance(value, int):
        return {"key": key, "type": "int64", "value": value}
    if isinstance(value, float):
        return {"key": key, "type": "float64", "value": value}
    return {"key": key, "type": "string", "value": str(value)}


def _jaeger_span(
    *,
    trace_id: str,
    span_id: str,
    operation_name: str,
    process_id: str,
    parent_span_id: str | None = None,
    start_us_offset: int = 0,
    duration_us: int = 5_000,
    status_error: bool = False,
    status_message: str = "",
    tags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tag_list = [_jaeger_tag(k, v) for k, v in (tags or {}).items()]
    if status_error:
        tag_list.append(_jaeger_tag("otel.status_code", "ERROR"))
        if status_message:
            tag_list.append(_jaeger_tag("otel.status_description", status_message))
    refs = []
    if parent_span_id:
        refs.append({"refType": "CHILD_OF", "traceID": trace_id, "spanID": parent_span_id})
    return {
        "traceID": trace_id,
        "spanID": span_id,
        "operationName": operation_name,
        "processID": process_id,
        "references": refs,
        "startTime": T0_US + start_us_offset,
        "duration": duration_us,
        "tags": tag_list,
        "logs": [],
    }


def jaeger_search_response_realistic() -> dict[str, Any]:
    """Multi-trace Jaeger search response with realistic noise:
      - typed tags (int64, bool)
      - operationName with embedded order_id (path parameter pathology)
      - one trace with a downstream_error shape
      - one trace with a retry_storm shape (3 attempts)
      - one trace with an orphan span (parent not in this batch — sampled out)
    """
    traces: list[dict[str, Any]] = []

    # Trace 1: downstream_error, path-parameter operation name
    traces.append({
        "traceID": "abcdef0000000001",
        "processes": {
            "p1": {"serviceName": "payment-service", "tags": []},
            "p2": {"serviceName": "inventory-service", "tags": []},
        },
        "spans": [
            _jaeger_span(
                trace_id="abcdef0000000001",
                span_id="s1",
                operation_name="POST /checkout/order-12345",
                process_id="p1",
                status_error=True,
                status_message="downstream failure",
                tags={"http.status_code": 503, "http.method": "POST"},
            ),
            _jaeger_span(
                trace_id="abcdef0000000001",
                span_id="s2",
                operation_name="inventory.reserve",
                process_id="p2",
                parent_span_id="s1",
                start_us_offset=10_000,
                duration_us=8_000,
                status_error=True,
                status_message="reserve failed",
                tags={"http.status_code": 503},
            ),
        ],
    })

    # Trace 2: retry_storm, 3 attempts (intentionally low to exercise
    # the post-fix fingerprint stability)
    retry_spans = []
    for i in range(1, 4):
        retry_spans.append(
            _jaeger_span(
                trace_id="abcdef0000000002",
                span_id=f"a{i}",
                operation_name="inventory.reserve_attempt",
                process_id="p2",
                start_us_offset=i * 60_000,
                duration_us=3_000,
                status_error=True,
                status_message="upstream 503",
                tags={
                    "retry.attempt": i,
                    "retry.max_attempts": 5,
                    "retry.backoff_ms": 50 * (2 ** (i - 1)),
                    "retry.policy": "exponential",
                    "retry.reason": "upstream 503",
                    "retry.retriable": True,
                },
            )
        )
    traces.append({
        "traceID": "abcdef0000000002",
        "processes": {"p2": {"serviceName": "inventory-service", "tags": []}},
        "spans": retry_spans,
    })

    # Trace 3: orphan span (parent_span_id references a span not in
    # this batch — common with tail sampling).
    traces.append({
        "traceID": "abcdef0000000003",
        "processes": {"p2": {"serviceName": "inventory-service", "tags": []}},
        "spans": [
            _jaeger_span(
                trace_id="abcdef0000000003",
                span_id="orphan",
                operation_name="inventory.reserve",
                process_id="p2",
                parent_span_id="missing-parent",
                status_error=True,
                status_message="reserve failed",
                tags={"http.status_code": 500},
            ),
        ],
    })

    return {"data": traces, "total": len(traces), "limit": 20, "offset": 0}


# ---------- Loki query response shape -------------------------------


def _loki_line(trace_id: str | None, message: str, *, json_body: bool = False) -> str:
    if json_body and trace_id:
        return json.dumps({"trace_id": trace_id, "msg": message})
    if json_body:
        return json.dumps({"msg": message})
    return message


def loki_streams_response_realistic() -> dict[str, Any]:
    """A Loki response covering the same trace_ids as the Jaeger fixture,
    with mixed labelling pathologies:
      - one stream where labels carry trace_id (clean case)
      - one stream where labels DO NOT carry trace_id; trace_id is in
        the JSON body of the log line
      - one stream with free-text log lines and no trace_id anywhere
        (common for older log shapes)
    """
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {
                        "service_name": "payment-service",
                        "level": "error",
                        "trace_id": "abcdef0000000001",
                    },
                    "values": [
                        [str(T0_NS + 12_000_000), "checkout failed: downstream 503"],
                    ],
                },
                {
                    "stream": {
                        "service_name": "inventory-service",
                        "level": "error",
                    },
                    "values": [
                        [
                            str(T0_NS + 60_000_000),
                            _loki_line("abcdef0000000002", "reserve_attempt: upstream 503", json_body=True),
                        ],
                        [
                            str(T0_NS + 120_000_000),
                            _loki_line("abcdef0000000002", "reserve_attempt: upstream 503", json_body=True),
                        ],
                    ],
                },
                {
                    "stream": {
                        "service_name": "payment-service",
                        "level": "warn",
                    },
                    "values": [
                        [str(T0_NS + 200_000_000), "rate limiter near threshold"],
                    ],
                },
            ],
        },
    }


# ---------- GHA artifact zip ---------------------------------------


def build_gha_artifact_zip(
    bundles: list[dict[str, Any]],
    *,
    layout: str = "directory",
) -> bytes:
    """Build an in-memory GHA artifact zip.

    `layout` shapes how an operator's pipeline might have arranged
    things inside the artifact:
      - 'directory': one .json file per trace under traces/
      - 'jsonl':     a single bundles.jsonl
      - 'nested':    timestamp-partitioned subdirectories
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if layout == "jsonl":
            content = "\n".join(json.dumps(b) for b in bundles) + "\n"
            zf.writestr("bundles.jsonl", content)
        elif layout == "directory":
            for i, b in enumerate(bundles):
                zf.writestr(f"traces/{i:04d}.json", json.dumps(b))
        elif layout == "nested":
            for i, b in enumerate(bundles):
                day = (datetime(2026, 5, 20) + timedelta(days=i % 3)).strftime("%Y-%m-%d")
                zf.writestr(f"traces/{day}/trace-{i:04d}.json", json.dumps(b))
        else:
            raise ValueError(f"unknown layout: {layout}")
    return buf.getvalue()


def write_gha_artifact(path: Path, bundles: list[dict[str, Any]], *, layout: str = "directory") -> None:
    path.write_bytes(build_gha_artifact_zip(bundles, layout=layout))


# ---------- partial gzip writer ------------------------------------


def write_partial_gzip(path: Path, full_payload: bytes, *, truncate_to: int) -> None:
    """Write a complete gzip stream then chop the tail off.

    Real-world cause: a writer that died mid-flush, or a file copied
    while still being written. The resulting file is a valid gzip
    prefix that decompresses to a partial payload (the part of the
    payload that fit inside the already-written gzip blocks).
    """
    buf = io.BytesIO()
    with gzip.open(buf, "wb") as gz:
        gz.write(full_payload)
    full = buf.getvalue()
    chopped = full[: max(1, min(truncate_to, len(full)))]
    path.write_bytes(chopped)
