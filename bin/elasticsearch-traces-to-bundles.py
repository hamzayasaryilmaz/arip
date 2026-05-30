#!/usr/bin/env python3
"""Convert Elasticsearch span/trace documents → JSONL trace bundles.

Many teams store OpenTelemetry spans (or Zipkin-style spans) in
Elasticsearch indexes — either via the OTel Collector's ES exporter,
APM Server, or custom pipelines. This adapter scrapes such indexes
into the JSONL trace-bundle format that `arip observe` consumes.

ARIP cannot infer trace structure from unstructured logs — it
requires SPAN-shaped documents with at least:
  - trace_id (or traceId, trace.id — configurable)
  - span_id  (or spanId, span.id)
  - service name
  - operation name
  - start time
  - parent_span_id (where applicable, to reconstruct the tree)

If your ES has only unstructured logs, this adapter cannot help —
you need distributed tracing instrumentation first. ARIP will
fail-fast with a `no_propagation` prerequisite failure if you try
to feed it logs as if they were spans.

Two input modes:

  1. **Live ES query** — pass --es-url + --index + --query (JSON).
     The adapter pages through hits and converts them.

  2. **Pre-pulled NDJSON** — pass --in pointing at a JSON or NDJSON
     file of hit documents (e.g. dumped via `elasticsearch-dump`).
     Use this when you can't expose ES directly or want to test.

Operator workflow:

    # Option A: live query (read-only — only GETs)
    python3 bin/elasticsearch-traces-to-bundles.py \\
      --es-url https://es.internal:9200 \\
      --index "apm-*-span-*" \\
      --query '{"range":{"@timestamp":{"gte":"now-1h"}}}' \\
      --out /tmp/bundles.jsonl

    # Option B: pre-pulled file
    python3 bin/elasticsearch-traces-to-bundles.py \\
      --in es-dump.ndjson \\
      --out /tmp/bundles.jsonl

    # Field mapping (defaults match OTel/APM convention; override if your
    # schema differs):
    python3 bin/elasticsearch-traces-to-bundles.py \\
      --in es-dump.ndjson \\
      --out /tmp/bundles.jsonl \\
      --trace-id-field traceID \\
      --span-id-field spanID \\
      --service-field "service.name"

This is operator tooling — NOT part of `arip_core`. The observation
module is unchanged; this script bridges Elasticsearch's storage
shape to the JSONL trace-bundle format that JsonlTraceSource
already accepts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ─── Defaults match the most common OTel-via-ES and APM Server schemas ───
DEFAULT_TRACE_ID_FIELDS = ["trace_id", "trace.id", "traceID", "traceId"]
DEFAULT_SPAN_ID_FIELDS = ["span_id", "span.id", "spanID", "spanId"]
DEFAULT_PARENT_FIELDS = ["parent_span_id", "parent.id", "parentSpanID", "parentSpanId"]
DEFAULT_SERVICE_FIELDS = ["service.name", "service_name", "resource.service.name"]
DEFAULT_OPERATION_FIELDS = ["name", "operation_name", "operation.name", "span.name"]
DEFAULT_TIMESTAMP_FIELDS = ["@timestamp", "timestamp", "start_time", "startTime"]
DEFAULT_DURATION_FIELDS = ["duration_us", "duration", "span.duration.us", "elapsed_us"]
DEFAULT_STATUS_FIELDS = ["status.code", "otel.status_code", "status"]


def _dig(doc: dict[str, Any], dotted_key: str) -> Any:
    """Resolve a dotted path through nested dicts.

    Handles both flat (`service.name` as literal key) and nested
    (`service: {name: ...}`) representations — ES indexes both
    depending on the dynamic-mapping flatten settings."""
    if dotted_key in doc:
        return doc[dotted_key]
    cur: Any = doc
    for part in dotted_key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _first_present(doc: dict[str, Any], fields: list[str]) -> Any:
    """Try each field in order; return the first non-None value."""
    for f in fields:
        v = _dig(doc, f)
        if v is not None:
            return v
    return None


def _to_iso(v: Any) -> str | None:
    """Normalise ES timestamps (string ISO, epoch_millis, epoch_micros)."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        # Heuristic: > 1e15 = micros, > 1e12 = millis, else seconds.
        if v > 1e15:
            ts = v / 1e6
        elif v > 1e12:
            ts = v / 1e3
        else:
            ts = float(v)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return None


def _duration_us(v: Any) -> int:
    """Coerce ES duration field. APM uses microseconds; some pipelines
    use nanoseconds. Heuristic: > 1e9 = ns, > 1e6 = us, else ms→us."""
    if v is None:
        return 0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    if n > 1e9:
        return int(n / 1000)  # ns → us
    if n > 1e6:
        return int(n)  # us
    return int(n * 1000)  # ms → us


def _status(v: Any) -> tuple[str, str]:
    """Normalise OTLP-style or APM status to (status, message)."""
    if v is None:
        return ("OK", "")
    if isinstance(v, str):
        upper = v.upper()
        if upper in ("ERROR", "STATUS_CODE_ERROR"):
            return ("ERROR", "")
        return ("OK", "")
    if isinstance(v, int):
        # OTLP: 2 = ERROR, 1 = OK, 0 = UNSET
        return ("ERROR", "") if v == 2 else ("OK", "")
    if isinstance(v, dict):
        code = v.get("code")
        msg = v.get("message", "") or ""
        if code in (2, "ERROR", "STATUS_CODE_ERROR"):
            return ("ERROR", msg)
        return ("OK", msg)
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
    trace_id = _first_present(doc, cfg.trace_id)
    span_id = _first_present(doc, cfg.span_id)
    if not trace_id or not span_id:
        return None
    start_iso = _to_iso(_first_present(doc, cfg.timestamp))
    if not start_iso:
        return None
    parent = _first_present(doc, cfg.parent)
    service = _first_present(doc, cfg.service) or "unknown"
    operation = _first_present(doc, cfg.operation) or ""
    duration = _duration_us(_first_present(doc, cfg.duration))
    status_str, status_msg = _status(_first_present(doc, cfg.status))

    # Span attributes: everything else (best-effort flat extraction)
    attributes: dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_index", "_id", "_score", "_source"}:
            continue
        # Skip already-extracted fields
        if any(k in flist for flist in [cfg.trace_id, cfg.span_id, cfg.parent,
                                         cfg.service, cfg.operation, cfg.timestamp,
                                         cfg.duration, cfg.status]):
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


def _hits_from_es(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    """Live ES query path. Pages with the search_after pattern.

    Read-only — only GET /index/_search. Never writes to ES."""
    import httpx

    base = args.es_url.rstrip("/")
    url = f"{base}/{args.index}/_search"
    body: dict[str, Any] = {
        "size": args.page_size,
        "sort": [{"@timestamp": "asc"}, "_id"],
    }
    if args.query:
        body["query"] = json.loads(args.query)

    auth = None
    if args.basic_auth:
        u, _, p = args.basic_auth.partition(":")
        auth = (u, p)

    headers = {"Content-Type": "application/json"}
    search_after: list[Any] | None = None
    total_yielded = 0
    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        while total_yielded < args.max_hits:
            if search_after:
                body["search_after"] = search_after
            resp = client.post(url, json=body, headers=headers, auth=auth)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
            if not hits:
                return
            for h in hits:
                source = h.get("_source") or h
                yield source
                total_yielded += 1
                if total_yielded >= args.max_hits:
                    return
            search_after = hits[-1].get("sort")
            if not search_after:
                return


def _hits_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """File path can be:
    - JSON: { "hits": { "hits": [...] } } (raw ES response)
    - JSON: [ {doc}, {doc}, ... ] (list of docs)
    - NDJSON: one doc per line

    Tries each format in order. NDJSON fallback runs if both single-JSON
    attempts fail — important because NDJSON's first character is also
    `{` so the JSON parse attempt looks plausible until it actually fails.
    """
    text = path.read_text()
    stripped = text.strip()
    if not stripped:
        return
    # Try single-JSON object (raw ES response or single doc)
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            hits = payload.get("hits", {}).get("hits") if isinstance(payload, dict) else None
            if isinstance(hits, list):
                for h in hits:
                    yield h.get("_source") or h
                return
            if isinstance(payload, dict):
                yield payload
                return
        except json.JSONDecodeError:
            pass  # fall through to NDJSON
    # Try JSON array
    if stripped.startswith("["):
        try:
            arr = json.loads(stripped)
            if isinstance(arr, list):
                for d in arr:
                    if isinstance(d, dict):
                        yield d.get("_source") or d
                return
        except json.JSONDecodeError:
            pass  # fall through to NDJSON
    # NDJSON — one document per line
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
    src.add_argument("--in", dest="src_file", type=Path, help="Pre-pulled hits file (JSON/NDJSON)")
    src.add_argument("--es-url", help="Live ES URL (e.g. https://es:9200)")

    p.add_argument("--index", help="ES index pattern (required with --es-url)")
    p.add_argument("--query", help="ES query JSON (paired with --es-url)")
    p.add_argument("--page-size", type=int, default=500, help="Hits per ES request (default 500)")
    p.add_argument("--max-hits", type=int, default=5000, help="Cap total hits pulled (default 5000)")
    p.add_argument("--basic-auth", help="user:pass for ES basic auth")
    p.add_argument("--insecure", action="store_true", help="Skip TLS verification")

    p.add_argument("--out", type=Path, required=True, help="Output JSONL bundles")

    # Field mapping overrides
    p.add_argument("--trace-id-field", help=f"Default tries: {DEFAULT_TRACE_ID_FIELDS}")
    p.add_argument("--span-id-field", help=f"Default tries: {DEFAULT_SPAN_ID_FIELDS}")
    p.add_argument("--parent-field", help=f"Default tries: {DEFAULT_PARENT_FIELDS}")
    p.add_argument("--service-field", help=f"Default tries: {DEFAULT_SERVICE_FIELDS}")
    p.add_argument("--operation-field", help=f"Default tries: {DEFAULT_OPERATION_FIELDS}")
    p.add_argument("--timestamp-field", help=f"Default tries: {DEFAULT_TIMESTAMP_FIELDS}")
    p.add_argument("--duration-field", help=f"Default tries: {DEFAULT_DURATION_FIELDS}")
    p.add_argument("--status-field", help=f"Default tries: {DEFAULT_STATUS_FIELDS}")

    args = p.parse_args(argv)

    if args.es_url and not args.index:
        p.error("--es-url requires --index")

    cfg = _FieldConfig(args)
    docs = _hits_from_es(args) if args.es_url else _hits_from_file(args.src_file)

    # Group spans by trace_id into bundles
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
        f"wrote {written} trace bundle(s) ({sum(len(s) for s in spans_by_trace.values())} spans), "
        f"skipped {skipped} unparseable doc(s) → {args.out}\n"
    )
    if skipped > 0 and written == 0:
        sys.stderr.write(
            "WARNING: zero bundles written but docs were present. "
            "Likely cause: field mapping mismatch. Check your ES schema "
            "and pass --trace-id-field / --span-id-field / --service-field "
            "to point at the right fields.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
