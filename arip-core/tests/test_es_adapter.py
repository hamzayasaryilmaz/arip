"""Tests for the Elasticsearch operator-side adapters.

ES adapter parallels Jaeger/Tempo/Loki adapters: it lives in bin/,
NOT in arip_core. These tests exercise the bin/ scripts via
subprocess so they match exactly what the operator invokes.

The adapters cover two cases:
  - traces: ES documents with span shape → JSONL bundles
  - logs: ES log documents → joined into existing bundles by trace_id
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ES_TRACES_TOOL = REPO_ROOT / "bin" / "elasticsearch-traces-to-bundles.py"
ES_LOGS_TOOL = REPO_ROOT / "bin" / "elasticsearch-logs-to-bundles.py"


def _run(tool: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tool), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _es_response(hits: list[dict]) -> dict:
    """Realistic ES response shape: {hits: {hits: [{_source: {...}}, ...]}}"""
    return {
        "took": 5,
        "hits": {
            "total": {"value": len(hits), "relation": "eq"},
            "hits": [
                {"_index": "apm-spans", "_id": str(i), "_source": h} for i, h in enumerate(hits)
            ],
        },
    }


def _otel_span_doc(
    *,
    trace_id: str = "abcdef0123456789",
    span_id: str = "01234567",
    parent: str | None = None,
    service: str = "payment-service",
    op: str = "handle_charge",
    duration_us: int = 5000,
    status: str = "OK",
) -> dict:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent,
        "service.name": service,
        "name": op,
        "@timestamp": "2026-05-30T10:00:00.000Z",
        "duration_us": duration_us,
        "status.code": status,
        "http.method": "POST",
        "http.status_code": 200 if status == "OK" else 500,
    }


# ---------- traces adapter ---------------------------------------


def test_traces_adapter_groups_spans_into_bundles(tmp_path: Path) -> None:
    """Multiple span documents sharing trace_id → one bundle with N spans."""
    src = tmp_path / "es-spans.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    _otel_span_doc(trace_id="trace-1", span_id="span-1"),
                    _otel_span_doc(trace_id="trace-1", span_id="span-2", parent="span-1"),
                    _otel_span_doc(trace_id="trace-2", span_id="span-3"),
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"

    r = _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr

    lines = dst.read_text().splitlines()
    assert len(lines) == 2  # one bundle per trace_id

    bundles_by_tid = {json.loads(l)["trace_id"]: json.loads(l) for l in lines}
    assert len(bundles_by_tid["trace-1"]["spans"]) == 2
    assert len(bundles_by_tid["trace-2"]["spans"]) == 1


def test_traces_adapter_handles_ndjson_input(tmp_path: Path) -> None:
    """NDJSON: one document per line."""
    src = tmp_path / "es-spans.ndjson"
    with src.open("w") as f:
        for i in range(3):
            doc = _otel_span_doc(trace_id=f"t-{i}", span_id=f"s-{i}")
            # Operator may dump with or without _source wrapper
            f.write(json.dumps({"_source": doc}) + "\n")
    dst = tmp_path / "bundles.jsonl"
    r = _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr
    assert len(dst.read_text().splitlines()) == 3


def test_traces_adapter_handles_list_input(tmp_path: Path) -> None:
    """Some dumpers output a plain JSON array of source docs."""
    src = tmp_path / "es-array.json"
    docs = [_otel_span_doc(trace_id=f"t-{i}", span_id=f"s-{i}") for i in range(2)]
    src.write_text(json.dumps(docs))
    dst = tmp_path / "bundles.jsonl"
    r = _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr
    assert len(dst.read_text().splitlines()) == 2


def test_traces_adapter_normalises_otel_status_code(tmp_path: Path) -> None:
    """OTLP status code 2 → 'ERROR' in the converted span."""
    src = tmp_path / "es.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "service.name": "svc",
                        "name": "op",
                        "@timestamp": "2026-05-30T10:00:00Z",
                        "duration_us": 1000,
                        "status.code": 2,  # OTLP ERROR
                    },
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["status"] == "ERROR"


def test_traces_adapter_handles_nested_service_name(tmp_path: Path) -> None:
    """ES with nested object representation: service: {name: '...'}"""
    src = tmp_path / "es.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "service": {"name": "nested-svc"},
                        "name": "op",
                        "@timestamp": "2026-05-30T10:00:00Z",
                        "duration_us": 1000,
                    },
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["service_name"] == "nested-svc"


def test_traces_adapter_normalises_epoch_millis_timestamp(tmp_path: Path) -> None:
    """ES @timestamp can be epoch_millis instead of ISO string."""
    src = tmp_path / "es.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "service.name": "svc",
                        "name": "op",
                        "@timestamp": 1748599200000,  # 2025-05-30T10:00:00Z in ms
                        "duration_us": 1000,
                    },
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    # Should parse, not crash, not be empty
    assert "2025" in bundle["spans"][0]["start_time"]


def test_traces_adapter_field_override(tmp_path: Path) -> None:
    """--service-field override picks up a non-default field name."""
    src = tmp_path / "es.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace_id": "t1",
                        "span_id": "s1",
                        "my_custom_service_field": "weird-svc",
                        "name": "op",
                        "@timestamp": "2026-05-30T10:00:00Z",
                        "duration_us": 1000,
                    },
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run(
        ES_TRACES_TOOL,
        "--in",
        str(src),
        "--out",
        str(dst),
        "--service-field",
        "my_custom_service_field",
    )
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["service_name"] == "weird-svc"


def test_traces_adapter_warns_when_all_docs_unparseable(tmp_path: Path) -> None:
    """Zero bundles + non-zero skipped → warn + exit non-zero."""
    src = tmp_path / "es.json"
    src.write_text(
        json.dumps(
            _es_response(
                [
                    {"random": "field", "no": "trace_id"},
                    {"another": "doc", "still": "no trace"},
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    r = _run(ES_TRACES_TOOL, "--in", str(src), "--out", str(dst))
    assert r.returncode != 0
    assert "WARNING" in r.stderr or "field mapping" in r.stderr.lower()


# ---------- logs adapter -----------------------------------------


def test_logs_adapter_joins_logs_into_bundles(tmp_path: Path) -> None:
    """Logs with trace_id matching a bundle's trace_id → attached."""
    # First create a bundle file
    bundles_path = tmp_path / "bundles.jsonl"
    with bundles_path.open("w") as f:
        f.write(
            json.dumps(
                {
                    "trace_id": "t-1",
                    "captured_at": "2026-05-30T10:00:00Z",
                    "spans": [
                        {
                            "trace_id": "t-1",
                            "span_id": "s1",
                            "service_name": "svc",
                            "operation_name": "op",
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
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "trace_id": "t-2",
                    "captured_at": "2026-05-30T10:00:01Z",
                    "spans": [
                        {
                            "trace_id": "t-2",
                            "span_id": "s2",
                            "service_name": "svc",
                            "operation_name": "op",
                            "start_time": "2026-05-30T10:00:01Z",
                            "duration_us": 1000,
                            "status": "OK",
                            "status_message": "",
                            "attributes": {},
                            "events": [],
                        }
                    ],
                    "logs": [],
                }
            )
            + "\n"
        )

    # Create ES logs source
    logs_src = tmp_path / "logs.json"
    logs_src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace_id": "t-1",
                        "service.name": "svc",
                        "level": "ERROR",
                        "message": "matched log",
                        "@timestamp": "2026-05-30T10:00:00.5Z",
                    },
                    {
                        "trace_id": "no-match",
                        "service.name": "svc",
                        "level": "INFO",
                        "message": "unmatched",
                        "@timestamp": "2026-05-30T10:00:00.6Z",
                    },
                ]
            )
        )
    )

    out = tmp_path / "bundles-with-logs.jsonl"
    unmatched = tmp_path / "unmatched.jsonl"
    r = _run(
        ES_LOGS_TOOL,
        "--in",
        str(logs_src),
        "--bundles",
        str(bundles_path),
        "--out",
        str(out),
        "--unmatched-out",
        str(unmatched),
    )
    assert r.returncode == 0, r.stderr

    joined = [json.loads(l) for l in out.read_text().splitlines()]
    by_tid = {b["trace_id"]: b for b in joined}
    assert len(by_tid["t-1"]["logs"]) == 1
    assert by_tid["t-1"]["logs"][0]["message"] == "matched log"
    assert len(by_tid["t-2"]["logs"]) == 0

    unmatched_lines = unmatched.read_text().splitlines()
    assert any("unmatched" in line for line in unmatched_lines)


def test_logs_adapter_handles_nested_trace_id_field(tmp_path: Path) -> None:
    """APM Server normalises trace_id under `trace.id` (nested)."""
    bundles_path = tmp_path / "b.jsonl"
    bundles_path.write_text(
        json.dumps(
            {
                "trace_id": "tid-nested",
                "captured_at": "2026-05-30T10:00:00Z",
                "spans": [
                    {
                        "trace_id": "tid-nested",
                        "span_id": "s",
                        "service_name": "x",
                        "operation_name": "o",
                        "start_time": "2026-05-30T10:00:00Z",
                        "duration_us": 1,
                        "status": "OK",
                        "status_message": "",
                        "attributes": {},
                        "events": [],
                    }
                ],
                "logs": [],
            }
        )
        + "\n"
    )

    logs_src = tmp_path / "logs.json"
    logs_src.write_text(
        json.dumps(
            _es_response(
                [
                    {
                        "trace": {"id": "tid-nested"},
                        "service.name": "x",
                        "level": "info",
                        "message": "ok",
                        "@timestamp": "2026-05-30T10:00:00Z",
                    },
                ]
            )
        )
    )

    out = tmp_path / "out.jsonl"
    r = _run(ES_LOGS_TOOL, "--in", str(logs_src), "--bundles", str(bundles_path), "--out", str(out))
    assert r.returncode == 0, r.stderr
    bundle = json.loads(out.read_text().splitlines()[0])
    assert len(bundle["logs"]) == 1
