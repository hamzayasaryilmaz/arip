"""Loki adapter — fallback chain regression tests.

Field test (arip-fieldtest/) surfaced two real-world cases the adapter
silently dropped:

  1. OTel Python SDK's Loki exporter writes the trace id field as
     `traceid` (lowercase, no underscore) inside the JSON log body. The
     adapter only tried `trace_id` and `traceID` → 100% of logs from
     OTel-instrumented Python apps were dropped as unmatched.

  2. OTel-Collector's loki exporter sets `job` as the service label
     (mapping to OTEL_SERVICE_NAME), not `service_name`. The adapter
     fell through to `unknown`, leaving every log entry with
     `service_name=unknown`.

These tests pin both fallbacks so they don't regress.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOKI_TOOL = REPO_ROOT / "bin" / "loki-export-to-logs.py"


def _make_bundle(trace_id: str) -> dict:
    return {
        "trace_id": trace_id,
        "captured_at": "2026-05-30T10:00:00Z",
        "spans": [
            {
                "trace_id": trace_id,
                "span_id": "s1",
                "parent_span_id": None,
                "service_name": "api-gateway",
                "operation_name": "POST /checkout",
                "start_time": "2026-05-30T10:00:00Z",
                "duration_us": 1000,
                "status": "OK",
                "status_message": "",
                "attributes": {},
                "events": [],
            }
        ],
        "logs": [],
    }


def _make_loki(streams: list[dict]) -> dict:
    return {"status": "success", "data": {"resultType": "streams", "result": streams}}


def _run_adapter(tmp_path: Path, bundle: dict, loki: dict, extra: list[str] | None = None) -> dict:
    b = tmp_path / "bundles.jsonl"
    b.write_text(json.dumps(bundle) + "\n")
    l = tmp_path / "loki.json"
    l.write_text(json.dumps(loki))
    out = tmp_path / "out.jsonl"
    cmd = [sys.executable, str(LOKI_TOOL), "--in", str(l), "--bundles", str(b), "--out", str(out)]
    if extra:
        cmd.extend(extra)
    subprocess.run(cmd, check=True, capture_output=True)
    return json.loads(out.read_text().splitlines()[0])


def test_lowercase_traceid_body_field_is_joined(tmp_path: Path) -> None:
    """OTel Python SDK Loki exporter writes `traceid` (no underscore)."""
    trace_id = "abc123def456"
    bundle = _make_bundle(trace_id)
    loki = _make_loki(
        [
            {
                "stream": {"job": "api-gateway", "level": "INFO"},
                "values": [
                    [
                        "1780000000000000000",
                        json.dumps(
                            {
                                "body": "checkout=ok",
                                "traceid": trace_id,
                                "spanid": "s1",
                                "severity": "INFO",
                            }
                        ),
                    ]
                ],
            }
        ]
    )
    result = _run_adapter(tmp_path, bundle, loki)
    assert len(result["logs"]) == 1, "lowercase `traceid` in body must be recognised"


def test_job_label_extracted_as_service_name(tmp_path: Path) -> None:
    """OTel-Collector loki exporter uses `job` as the service-name label."""
    trace_id = "deadbeef00112233"
    bundle = _make_bundle(trace_id)
    loki = _make_loki(
        [
            {
                "stream": {"job": "payment-service", "level": "WARN"},
                "values": [
                    [
                        "1780000000000000000",
                        json.dumps({"body": "card declined", "traceid": trace_id}),
                    ]
                ],
            }
        ]
    )
    result = _run_adapter(tmp_path, bundle, loki)
    assert len(result["logs"]) == 1
    assert result["logs"][0]["service_name"] == "payment-service", (
        "service_name must be derived from `job` label, not default to `unknown`"
    )


def test_attributes_subdict_trace_id_resolved(tmp_path: Path) -> None:
    """OTel emits trace_id within an `attributes` sub-dict too."""
    trace_id = "f00ba00ba00ba00b"
    bundle = _make_bundle(trace_id)
    loki = _make_loki(
        [
            {
                "stream": {"job": "order-service"},
                "values": [
                    [
                        "1780000000000000000",
                        json.dumps(
                            {
                                "body": "no traceid at top level",
                                "attributes": {"otelTraceID": trace_id, "code.function": "x"},
                            }
                        ),
                    ]
                ],
            }
        ]
    )
    result = _run_adapter(tmp_path, bundle, loki)
    assert len(result["logs"]) == 1, (
        "trace_id must also be discovered inside the `attributes` sub-dict"
    )
