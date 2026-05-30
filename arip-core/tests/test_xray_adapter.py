"""Tests for the AWS X-Ray adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "bin" / "aws-xray-to-bundles.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _xray_segment(
    *,
    seg_id="0123456789abcdef",
    name="payment-service",
    parent_id=None,
    start=1748599200.0,
    end=1748599200.05,
    error=False,
    fault=False,
    subsegments=None,
    http=None,
    aws=None,
) -> dict:
    seg = {
        "Id": seg_id,
        "Name": name,
        "StartTime": start,
        "EndTime": end,
    }
    if parent_id:
        seg["ParentId"] = parent_id
    if error:
        seg["Error"] = True
    if fault:
        seg["Fault"] = True
    if subsegments:
        seg["Subsegments"] = subsegments
    if http:
        seg["Http"] = http
    if aws:
        seg["Aws"] = aws
    return seg


def _xray_response(segments_per_trace: list[list[dict]]) -> dict:
    """X-Ray batch-get-traces shape: Traces[].Segments[].Document is JSON string."""
    return {
        "Traces": [
            {
                "Id": f"1-{i:08x}-{j:024x}".replace(f"{j:024x}", "abc" * 8)[:34],
                "Duration": 0.05,
                "Segments": [{"Id": s["Id"], "Document": json.dumps(s)} for s in segments],
            }
            for i, segments in enumerate(segments_per_trace, 1)
            for j in [1]  # noop, just to make traceID
        ],
        "UnprocessedTraceIds": [],
    }


def test_converts_single_segment_per_trace(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    src.write_text(
        json.dumps(
            _xray_response(
                [
                    [_xray_segment(seg_id="aaaa1111")],
                    [_xray_segment(seg_id="bbbb2222")],
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    r = _run("--in", str(src), "--out", str(dst))
    assert r.returncode == 0, r.stderr
    bundles = [json.loads(l) for l in dst.read_text().splitlines()]
    assert len(bundles) == 2
    assert all(len(b["spans"]) == 1 for b in bundles)


def test_subsegments_flattened_as_children(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    seg = _xray_segment(
        seg_id="parent-seg",
        subsegments=[
            _xray_segment(seg_id="child-1"),
            _xray_segment(seg_id="child-2", subsegments=[_xray_segment(seg_id="grandchild")]),
        ],
    )
    src.write_text(json.dumps(_xray_response([[seg]])))
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    span_ids = {s["span_id"] for s in bundle["spans"]}
    assert {"parent-seg", "child-1", "child-2", "grandchild"} <= span_ids
    # Parent-child correctness
    by_id = {s["span_id"]: s for s in bundle["spans"]}
    assert by_id["child-1"]["parent_span_id"] == "parent-seg"
    assert by_id["grandchild"]["parent_span_id"] == "child-2"


def test_error_segment_marked_as_ERROR(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    src.write_text(
        json.dumps(
            _xray_response(
                [
                    [_xray_segment(error=True)],
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["status"] == "ERROR"


def test_fault_segment_marked_as_ERROR(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    src.write_text(
        json.dumps(
            _xray_response(
                [
                    [_xray_segment(fault=True)],
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    assert bundle["spans"][0]["status"] == "ERROR"


def test_http_section_flattened_to_attributes(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    src.write_text(
        json.dumps(
            _xray_response(
                [
                    [
                        _xray_segment(
                            http={
                                "Request": {"Method": "POST", "URL": "/charge"},
                                "Response": {"Status": 500},
                            }
                        )
                    ],
                ]
            )
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    attrs = bundle["spans"][0]["attributes"]
    # Flatten preserves the original key casing (X-Ray uses PascalCase
    # but we only lowercase the top-level section name as a prefix).
    assert "http.Request.Method" in attrs
    assert attrs["http.Request.Method"] == "POST"
    assert attrs.get("http.Response.Status") == 500


def test_xray_trace_id_format_converted(tmp_path: Path) -> None:
    """X-Ray uses '1-{8hex}-{24hex}'; we strip the '1-' prefix and dashes."""
    src = tmp_path / "xray.json"
    src.write_text(
        json.dumps(
            {
                "Traces": [
                    {
                        "Id": "1-12345678-abcdef0123456789abcdef01",
                        "Duration": 0.05,
                        "Segments": [
                            {"Id": "ccc", "Document": json.dumps(_xray_segment(seg_id="ccc"))}
                        ],
                    }
                ]
            }
        )
    )
    dst = tmp_path / "bundles.jsonl"
    _run("--in", str(src), "--out", str(dst))
    bundle = json.loads(dst.read_text().splitlines()[0])
    # Stripped: "12345678abcdef0123456789abcdef01"
    assert bundle["trace_id"] == "12345678abcdef0123456789abcdef01"


def test_empty_input_writes_nothing_warns(tmp_path: Path) -> None:
    src = tmp_path / "xray.json"
    src.write_text(json.dumps({"Traces": [], "UnprocessedTraceIds": []}))
    dst = tmp_path / "bundles.jsonl"
    r = _run("--in", str(src), "--out", str(dst))
    assert r.returncode != 0
    assert "zero bundles" in r.stderr.lower()
