"""Tests for the operator-side Tempo OTLP-JSON adapter (bin/).

The adapter handles real Tempo `/api/traces/<id>` responses, which
differ from Jaeger's wire format:
  - traceId / spanId are base64-encoded bytes (not hex strings)
  - timestamps are `*UnixNano` strings (not microseconds)
  - attributes use OTLP wrappers (stringValue/intValue/boolValue/...)
  - top-level shape is `batches` → `resource` + `scopeSpans` → `spans`

These tests use realistic Tempo response shapes captured during
op003 validation. They run the bin/ script via subprocess so the
test exercises exactly what an operator would invoke.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPO_TOOL = REPO_ROOT / "bin" / "tempo-export-to-bundles.py"


def _b64(hex_str: str) -> str:
    """Convert a hex string to base64 (Tempo's wire format)."""
    return base64.b64encode(bytes.fromhex(hex_str)).decode("ascii")


def _run_tool(*args: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(TEMPO_TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"tempo-export-to-bundles.py failed (exit {proc.returncode}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )


def _make_tempo_response(
    trace_id_hex: str = "51d35010c2031e7d142ddc64ab519946",
    spans: list[dict] | None = None,
    service_name: str = "demo-service",
) -> dict:
    """Build a realistic Tempo `/api/traces/<id>` response."""
    if spans is None:
        spans = [
            {
                "traceId": _b64(trace_id_hex),
                "spanId": _b64("05e793140372fa88"),
                "parentSpanId": _b64("79e4d4bdb79c50fc"),
                "name": "handle_request",
                "startTimeUnixNano": "1780153620000000000",
                "endTimeUnixNano": "1780153620000057000",
                "attributes": [
                    {"key": "http.method", "value": {"stringValue": "GET"}},
                    {"key": "http.status_code", "value": {"intValue": "200"}},
                ],
                "status": {"code": 1, "message": ""},
            }
        ]
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "test-scope"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def test_tempo_adapter_converts_single_trace(tmp_path: Path) -> None:
    """A single Tempo trace response → one JSONL bundle."""
    src = tmp_path / "tempo.json"
    src.write_text(json.dumps(_make_tempo_response()))
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    lines = dst.read_text().splitlines()
    assert len(lines) == 1
    bundle = json.loads(lines[0])
    assert bundle["trace_id"] == "51d35010c2031e7d142ddc64ab519946"
    assert len(bundle["spans"]) == 1
    span = bundle["spans"][0]
    assert span["service_name"] == "demo-service"
    assert span["operation_name"] == "handle_request"
    # base64-decoded IDs match expected hex
    assert span["span_id"] == "05e793140372fa88"
    assert span["parent_span_id"] == "79e4d4bdb79c50fc"


def test_tempo_adapter_handles_otlp_attribute_types(tmp_path: Path) -> None:
    """OTLP attribute value wrappers (intValue/boolValue/stringValue/doubleValue)
    are coerced to plain JSON values."""
    src = tmp_path / "tempo.json"
    spans = [
        {
            "traceId": _b64("11" * 16),
            "spanId": _b64("aa" * 8),
            "name": "test",
            "startTimeUnixNano": "1780153620000000000",
            "endTimeUnixNano": "1780153620000010000",
            "attributes": [
                {"key": "str_attr", "value": {"stringValue": "hello"}},
                {"key": "int_attr", "value": {"intValue": "42"}},
                {"key": "bool_attr", "value": {"boolValue": True}},
                {"key": "double_attr", "value": {"doubleValue": 1.5}},
            ],
            "status": {"code": 1},
        }
    ]
    src.write_text(json.dumps(_make_tempo_response(spans=spans)))
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    bundle = json.loads(dst.read_text().splitlines()[0])
    attrs = bundle["spans"][0]["attributes"]
    assert attrs["str_attr"] == "hello"
    assert attrs["int_attr"] == 42
    assert attrs["bool_attr"] is True
    assert attrs["double_attr"] == 1.5


def test_tempo_adapter_maps_status_code(tmp_path: Path) -> None:
    """OTLP status code 2 → 'ERROR' status, message preserved."""
    src = tmp_path / "tempo.json"
    spans = [
        {
            "traceId": _b64("22" * 16),
            "spanId": _b64("bb" * 8),
            "name": "failing_op",
            "startTimeUnixNano": "1780153620000000000",
            "endTimeUnixNano": "1780153620000050000",
            "attributes": [],
            "status": {"code": 2, "message": "downstream returned 503"},
        }
    ]
    src.write_text(json.dumps(_make_tempo_response(spans=spans)))
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    span = json.loads(dst.read_text().splitlines()[0])["spans"][0]
    assert span["status"] == "ERROR"
    assert span["status_message"] == "downstream returned 503"


def test_tempo_adapter_handles_jsonl_input(tmp_path: Path) -> None:
    """JSONL input (one Tempo trace response per line) → JSONL bundles."""
    src = tmp_path / "tempo.jsonl"
    with src.open("w") as fh:
        for i in range(3):
            r = _make_tempo_response(
                trace_id_hex=f"{i:032x}",
                service_name=f"svc-{i}",
            )
            fh.write(json.dumps(r) + "\n")
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    lines = dst.read_text().splitlines()
    assert len(lines) == 3
    services = {json.loads(l)["spans"][0]["service_name"] for l in lines}
    assert services == {"svc-0", "svc-1", "svc-2"}


def test_tempo_adapter_skips_empty_batches(tmp_path: Path) -> None:
    """Empty `batches` array → no output bundle, no crash."""
    src = tmp_path / "tempo.json"
    src.write_text(json.dumps({"batches": []}))
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    assert dst.read_text() == ""


def test_tempo_adapter_handles_missing_service_name(tmp_path: Path) -> None:
    """A batch with no `service.name` resource attribute defaults to
    'unknown' rather than dropping the trace."""
    src = tmp_path / "tempo.json"
    payload = {
        "batches": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [
                    {
                        "scope": {"name": "s"},
                        "spans": [
                            {
                                "traceId": _b64("33" * 16),
                                "spanId": _b64("cc" * 8),
                                "name": "anon",
                                "startTimeUnixNano": "1780153620000000000",
                                "endTimeUnixNano": "1780153620000001000",
                                "attributes": [],
                                "status": {"code": 1},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    src.write_text(json.dumps(payload))
    dst = tmp_path / "bundles.jsonl"

    _run_tool("--in", str(src), "--out", str(dst))

    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["service_name"] == "unknown"


def test_tempo_adapter_observed_e2e_via_jsonl_source(tmp_path: Path) -> None:
    """End-to-end: Tempo response → adapter → JsonlTraceSource → observe.
    The bundle is consumable by the existing observation pipeline
    without any pipeline-side changes."""
    from arip_core.observation.pipeline import observe
    from arip_core.observation.sources import JsonlTraceSource
    from arip_core.observation.store import ObservationStore

    src = tmp_path / "tempo.json"
    src.write_text(json.dumps(_make_tempo_response()))
    dst = tmp_path / "bundles.jsonl"
    _run_tool("--in", str(src), "--out", str(dst))

    store = ObservationStore(tmp_path / "obs.db")
    summary = observe(source=JsonlTraceSource(dst), store=store, budget=10)
    assert summary.events_new == 1
