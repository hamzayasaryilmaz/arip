#!/usr/bin/env python3
"""Join Elasticsearch logs into existing JSONL trace bundles by trace_id.

Parallel to `bin/loki-export-to-logs.py` but for Elasticsearch as the
log backend. Many teams use ES for both spans and logs (especially
APM Server setups). This adapter pulls log documents and attaches
them to the trace bundles whose `trace_id` they match.

Behavior:
- Each ES log document is checked for a trace_id field (configurable).
- Matching logs are attached to the bundle's `logs` list.
- Unmatched logs go to --unmatched-out (operator can inspect what
  fell on the floor — never silently absorbed into a random bundle).

Operator workflow:

    # Live ES query
    python3 bin/elasticsearch-logs-to-bundles.py \\
      --es-url https://es.internal:9200 \\
      --index "logs-*" \\
      --query '{"range":{"@timestamp":{"gte":"now-1h"}}}' \\
      --bundles       /tmp/bundles.jsonl \\
      --out           /tmp/bundles-with-logs.jsonl \\
      --unmatched-out /tmp/unmatched-logs.jsonl

    # Or from a pre-pulled dump
    python3 bin/elasticsearch-logs-to-bundles.py \\
      --in es-logs-dump.ndjson \\
      --bundles       /tmp/bundles.jsonl \\
      --out           /tmp/bundles-with-logs.jsonl

If your log documents don't carry `trace_id`, this adapter cannot
join them — the engine will hit MIN_EVIDENCE_KINDS=2 abstention
for traces without log evidence. The right fix is upstream: add
trace_id to your logger's MDC / structured fields.

This is operator tooling — NOT part of `arip_core`. Same pattern
as the other adapters.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_TRACE_ID_FIELDS = [
    "trace_id", "trace.id", "traceID", "traceId",
    # APM Server normalises it under transaction.trace_id sometimes:
    "transaction.trace_id",
]
DEFAULT_SERVICE_FIELDS = ["service.name", "service_name", "kubernetes.container.name"]
DEFAULT_LEVEL_FIELDS = ["level", "log.level", "loglevel", "severity"]
DEFAULT_MESSAGE_FIELDS = ["message", "msg", "log.message", "log"]
DEFAULT_TIMESTAMP_FIELDS = ["@timestamp", "timestamp", "time"]


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


def _to_iso(v: Any) -> str:
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return datetime.now(tz=timezone.utc).isoformat()
    if isinstance(v, (int, float)):
        if v > 1e15:
            return datetime.fromtimestamp(v / 1e6, tz=timezone.utc).isoformat()
        if v > 1e12:
            return datetime.fromtimestamp(v / 1e3, tz=timezone.utc).isoformat()
        return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
    return datetime.now(tz=timezone.utc).isoformat()


class _Cfg:
    def __init__(self, args: argparse.Namespace) -> None:
        self.trace_id = [args.trace_id_field] if args.trace_id_field else DEFAULT_TRACE_ID_FIELDS
        self.service = [args.service_field] if args.service_field else DEFAULT_SERVICE_FIELDS
        self.level = [args.level_field] if args.level_field else DEFAULT_LEVEL_FIELDS
        self.message = [args.message_field] if args.message_field else DEFAULT_MESSAGE_FIELDS
        self.timestamp = [args.timestamp_field] if args.timestamp_field else DEFAULT_TIMESTAMP_FIELDS


def _log_from_doc(doc: dict[str, Any], cfg: _Cfg) -> dict[str, Any]:
    trace_id = _first(doc, cfg.trace_id)
    service = _first(doc, cfg.service) or "unknown"
    level = (_first(doc, cfg.level) or "INFO")
    if isinstance(level, str):
        level = level.upper()
    return {
        "timestamp": _to_iso(_first(doc, cfg.timestamp)),
        "service_name": str(service),
        "level": str(level),
        "message": str(_first(doc, cfg.message) or ""),
        "trace_id": str(trace_id) if trace_id else None,
        "fields": {k: v for k, v in doc.items() if isinstance(v, (str, int, float, bool))},
    }


def _hits_from_es(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
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
    total = 0
    with httpx.Client(timeout=30.0, verify=not args.insecure) as client:
        while total < args.max_hits:
            if search_after:
                body["search_after"] = search_after
            resp = client.post(url, json=body, headers=headers, auth=auth)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
            if not hits:
                return
            for h in hits:
                yield h.get("_source") or h
                total += 1
                if total >= args.max_hits:
                    return
            search_after = hits[-1].get("sort")
            if not search_after:
                return


def _hits_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """Same format-detection logic as the traces adapter — see its
    docstring. NDJSON fallback is the last resort."""
    text = path.read_text()
    if not text.strip():
        return
    stripped = text.strip()
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
    src.add_argument("--in", dest="src_file", type=Path)
    src.add_argument("--es-url")
    p.add_argument("--index")
    p.add_argument("--query")
    p.add_argument("--page-size", type=int, default=500)
    p.add_argument("--max-hits", type=int, default=10000)
    p.add_argument("--basic-auth")
    p.add_argument("--insecure", action="store_true")

    p.add_argument("--bundles", type=Path, required=True, help="Existing JSONL trace bundles to join into")
    p.add_argument("--out", type=Path, required=True, help="Output JSONL bundles with joined logs")
    p.add_argument("--unmatched-out", type=Path, default=None, help="Write unmatched logs here")

    p.add_argument("--trace-id-field")
    p.add_argument("--service-field")
    p.add_argument("--level-field")
    p.add_argument("--message-field")
    p.add_argument("--timestamp-field")

    args = p.parse_args(argv)
    if args.es_url and not args.index:
        p.error("--es-url requires --index")

    cfg = _Cfg(args)
    docs = _hits_from_es(args) if args.es_url else _hits_from_file(args.src_file)

    logs_by_trace: dict[str, list[dict[str, Any]]] = {}
    unmatched: list[dict[str, Any]] = []
    for doc in docs:
        log = _log_from_doc(doc, cfg)
        tid = log.get("trace_id")
        if tid:
            logs_by_trace.setdefault(tid, []).append(log)
        else:
            unmatched.append(log)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joined = 0
    bundles_seen = 0
    matched_trace_ids: set[str] = set()
    with args.bundles.open() as fh_in, args.out.open("w") as fh_out:
        for line in fh_in:
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
                bundle["logs"] = list(bundle.get("logs") or []) + extra
                joined += len(extra)
                matched_trace_ids.add(tid)
            fh_out.write(json.dumps(bundle))
            fh_out.write("\n")

    # Logs whose trace_id didn't match any bundle are unmatched too —
    # they had an ID but it pointed nowhere. Don't silently drop them.
    for tid, log_list in logs_by_trace.items():
        if tid not in matched_trace_ids:
            unmatched.extend(log_list)

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
