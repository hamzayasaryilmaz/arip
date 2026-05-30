"""Tests for the Honeycomb adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "bin" / "honeycomb-export-to-bundles.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _hc_event(
    *,
    trace_id="abc123",
    span_id="span-1",
    parent=None,
    service="payment-service",
    name="charge",
    timestamp="2026-05-30T10:00:00Z",
    duration_ms=42,
    status=None,
) -> dict:
    event = {
        "trace.trace_id": trace_id,
        "trace.span_id": span_id,
        "service.name": service,
        "name": name,
        "timestamp": timestamp,
        "duration_ms": duration_ms,
    }
    if parent:
        event["trace.parent_id"] = parent
    if status is not None:
        event["status_code"] = status
    return event


def _hc_response(events: list[dict]) -> dict:
    """Honeycomb query_results shape."""
    return {
        "complete": True,
        "data": {"results": events},
    }


def test_groups_events_into_bundles(tmp_path: Path) -> None:
    src = tmp_path / "hc.json"
    src.write_text(
        json.dumps(
            _hc_response(
                [
                    _hc_event(trace_id="t1", span_id="a"),
                    _hc_event(trace_id="t1", span_id="b", parent="a"),
                    _hc_event(trace_id="t2", span_id="c"),
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    r = _run("--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr
    bundles = [json.loads(l) for l in dst.read_text().splitlines()]
    assert len(bundles) == 2
    by_tid = {b["trace_id"]: b for b in bundles}
    assert len(by_tid["t1"]["spans"]) == 2
    assert len(by_tid["t2"]["spans"]) == 1


def test_duration_ms_converted_to_us(tmp_path: Path) -> None:
    src = tmp_path / "hc.json"
    src.write_text(json.dumps(_hc_response([_hc_event(duration_ms=50)])))
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["duration_us"] == 50000  # 50 ms = 50000 us


def test_status_code_string_error_recognized(tmp_path: Path) -> None:
    src = tmp_path / "hc.json"
    src.write_text(json.dumps(_hc_response([_hc_event(status="ERROR")])))
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["status"] == "ERROR"


def test_status_error_boolean_recognized(tmp_path: Path) -> None:
    """Some Honeycomb instrumentations use `error: true`."""
    src = tmp_path / "hc.json"
    event = _hc_event()
    event["error"] = True
    src.write_text(json.dumps(_hc_response([event])))
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst), "--status-field", "error")
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["status"] == "ERROR"


def test_skips_events_missing_required_fields(tmp_path: Path) -> None:
    src = tmp_path / "hc.json"
    src.write_text(
        json.dumps(
            _hc_response(
                [
                    {"random": "field"},
                    _hc_event(),
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    r = _run("--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr
    bundles = dst.read_text().splitlines()
    assert len(bundles) == 1


def test_warns_when_all_events_unparseable(tmp_path: Path) -> None:
    src = tmp_path / "hc.json"
    src.write_text(
        json.dumps(
            _hc_response(
                [
                    {"random": "field"},
                    {"another": "junk"},
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    r = _run("--in", str(src), "--out", str(dst))
    assert r.returncode != 0
    assert "field-mapping" in r.stderr.lower() or "WARNING" in r.stderr


def test_field_override_works(tmp_path: Path) -> None:
    """If user has custom span_id field, override resolves it."""
    src = tmp_path / "hc.json"
    custom_event = {
        "trace.trace_id": "tid",
        "my_custom_span_field": "sid",
        "service.name": "x",
        "name": "op",
        "timestamp": "2026-05-30T10:00:00Z",
        "duration_ms": 1,
    }
    src.write_text(json.dumps(_hc_response([custom_event])))
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst), "--span-id-field", "my_custom_span_field")
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["span_id"] == "sid"


def test_handles_jsonl_input(tmp_path: Path) -> None:
    src = tmp_path / "hc.jsonl"
    with src.open("w") as f:
        for i in range(3):
            f.write(json.dumps(_hc_event(trace_id=f"t{i}", span_id=f"s{i}")) + "\n")
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    assert len(dst.read_text().splitlines()) == 3
