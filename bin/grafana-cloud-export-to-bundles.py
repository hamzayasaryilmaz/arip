#!/usr/bin/env python3
"""Convert Grafana Cloud Tempo spans → ARIP JSONL trace bundles.

Grafana Cloud Tempo uses the same wire format as self-hosted
Tempo (OTLP JSON). This is a convenience wrapper around the
existing Tempo adapter that handles Grafana Cloud-specific:
  - Authentication (basic auth with stack ID + API key)
  - Endpoint URL pattern (tempo-prod-XX-prod-{region}.grafana.net)
  - Rate limit handling

For pre-pulled dumps (you already exported via the Grafana UI or
curl), use bin/tempo-export-to-bundles.py directly — the wire
format is identical.

Operator workflow:

  # Set credentials
  export GRAFANA_TEMPO_URL="https://tempo-prod-04-prod-eu-west-2.grafana.net"
  export GRAFANA_STACK_ID="123456"             # numeric ID
  export GRAFANA_API_KEY="glc_xxxxxxxxxxx"     # service account token

  # Live query path
  python3 bin/grafana-cloud-export-to-bundles.py \\
    --tempo-url $GRAFANA_TEMPO_URL \\
    --stack-id $GRAFANA_STACK_ID \\
    --api-key $GRAFANA_API_KEY \\
    --tags '{".service.name":"checkout"}' \\
    --limit 100 \\
    --out /tmp/bundles.jsonl

  # Pre-pulled dump path — delegates to tempo-export-to-bundles.py
  python3 bin/grafana-cloud-export-to-bundles.py \\
    --in /tmp/grafana-tempo-dump.jsonl \\
    --out /tmp/bundles.jsonl

  # Observe
  uv run arip observe /tmp/bundles.jsonl

Honest framing: this adapter is a thin wrapper. The actual span
conversion happens in tempo-export-to-bundles.py. The reason this
file exists is because Grafana Cloud's auth + URL pattern is
non-obvious and worth documenting separately.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


def _hits_from_grafana_cloud(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    """Live query Grafana Cloud Tempo.

    Two-step pattern (same as self-hosted Tempo):
    1. Discover trace IDs via /api/search?tags=...
    2. Fetch each trace via /api/traces/<trace_id>
    """
    import httpx

    base = args.tempo_url.rstrip("/")
    # Grafana Cloud uses basic auth: stack_id:api_key
    auth = (str(args.stack_id), args.api_key)
    headers = {"Accept": "application/json"}

    with httpx.Client(timeout=30.0, verify=not args.insecure, auth=auth) as client:
        # Step 1: search for trace IDs
        search_url = f"{base}/api/search"
        params: dict[str, Any] = {
            "tags": args.tags,
            "limit": args.limit,
        }
        if args.start_time:
            params["start"] = args.start_time
        if args.end_time:
            params["end"] = args.end_time

        resp = client.get(search_url, params=params, headers=headers)
        if resp.status_code == 401:
            sys.stderr.write(
                "ERROR: Grafana Cloud Tempo returned 401. "
                "Check that --stack-id is the numeric Grafana Cloud "
                "stack ID and --api-key is a service account token "
                "with `traces:read` permission.\n"
            )
            raise RuntimeError("authentication failed")
        if resp.status_code == 429:
            sys.stderr.write(
                "WARNING: Grafana Cloud rate-limited the request. "
                "Reduce --limit or query a narrower time range.\n"
            )
        resp.raise_for_status()

        trace_ids = [
            t.get("traceID")
            for t in (resp.json().get("traces") or [])
            if t.get("traceID")
        ]
        sys.stderr.write(f"discovered {len(trace_ids)} trace ID(s) from search\n")

        # Step 2: fetch each trace
        for i, tid in enumerate(trace_ids, 1):
            try:
                trace_resp = client.get(
                    f"{base}/api/traces/{tid}", headers=headers
                )
                trace_resp.raise_for_status()
            except httpx.HTTPError as exc:
                sys.stderr.write(f"  [{i}/{len(trace_ids)}] {tid}: skipped ({exc})\n")
                continue
            yield trace_resp.json()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])

    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--in", dest="src_file", type=Path,
                     help="Pre-pulled Tempo JSONL (delegates to tempo-export-to-bundles.py)")
    src.add_argument("--tempo-url",
                     help="Grafana Cloud Tempo URL (e.g. https://tempo-prod-04-prod-eu-west-2.grafana.net)")

    p.add_argument("--stack-id", help="Grafana Cloud stack ID (required with --tempo-url)")
    p.add_argument("--api-key", help="Grafana Cloud service account token (required with --tempo-url)")
    p.add_argument("--tags", default="", help='Tempo TraceQL tags (e.g. \'{".service.name":"checkout"}\')')
    p.add_argument("--start-time", help="Start time (unix epoch seconds)")
    p.add_argument("--end-time", help="End time (unix epoch seconds)")
    p.add_argument("--limit", type=int, default=100, help="Trace ID limit per search (default 100)")
    p.add_argument("--insecure", action="store_true")

    p.add_argument("--out", type=Path, required=True)

    args = p.parse_args(argv)

    # Pre-pulled file: delegate to tempo-export-to-bundles.py
    if args.src_file:
        tempo_tool = Path(__file__).parent / "tempo-export-to-bundles.py"
        if not tempo_tool.exists():
            sys.stderr.write(
                "ERROR: tempo-export-to-bundles.py not found alongside "
                "this script. Cannot delegate.\n"
            )
            return 1
        sys.stderr.write(
            "delegating to tempo-export-to-bundles.py (wire format identical)\n"
        )
        result = subprocess.run(
            [sys.executable, str(tempo_tool),
             "--in", str(args.src_file), "--out", str(args.out)],
            check=False,
        )
        return result.returncode

    # Live query: pull traces, write to temp file, delegate conversion
    if not args.stack_id or not args.api_key:
        p.error("--tempo-url requires --stack-id AND --api-key")

    # Write traces to a temp file as NDJSON
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        count = 0
        for trace_payload in _hits_from_grafana_cloud(args):
            tmp.write(json.dumps(trace_payload))
            tmp.write("\n")
            count += 1

    sys.stderr.write(f"pulled {count} trace(s) from Grafana Cloud → {tmp_path}\n")

    # Delegate to the Tempo adapter for the actual conversion
    tempo_tool = Path(__file__).parent / "tempo-export-to-bundles.py"
    result = subprocess.run(
        [sys.executable, str(tempo_tool),
         "--in", str(tmp_path), "--out", str(args.out)],
        check=False,
    )
    tmp_path.unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
