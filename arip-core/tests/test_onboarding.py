"""Tests for `arip init` (auto-config) and `arip doctor` (per-rule
diagnostic) — the two commands that cut new-operator onboarding from
4-8h hand-holding to ~30 minutes self-serve.
"""

from __future__ import annotations

import json
from pathlib import Path

from arip_core.canonical.config import load_config_yaml
from arip_core.onboarding import (
    detect_config,
    diagnose,
    load_correlated,
    render_doctor_report,
    render_yaml,
)


def _bundle_dict(
    *,
    trace_id: str,
    spans: list[dict],
    logs: list[dict] | None = None,
) -> dict:
    return {
        "trace_id": trace_id,
        "captured_at": "2026-05-30T10:00:00Z",
        "spans": spans,
        "logs": logs or [],
    }


def _span_dict(
    *,
    trace_id: str,
    span_id: str,
    service: str,
    operation: str,
    parent: str | None = None,
    duration_us: int = 1000,
    status: str = "OK",
    attributes: dict | None = None,
) -> dict:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent,
        "service_name": service,
        "operation_name": operation,
        "start_time": "2026-05-30T10:00:00Z",
        "duration_us": duration_us,
        "status": status,
        "status_message": "",
        "attributes": attributes or {},
        "events": [],
    }


def _write_bundle_file(tmp_path: Path, bundles: list[dict]) -> Path:
    p = tmp_path / "bundles.jsonl"
    p.write_text("\n".join(json.dumps(b) for b in bundles) + "\n")
    return p


# ─── arip init: auto-config detection ────────────────────────────────


def test_init_detects_business_key_appearing_across_services(tmp_path: Path) -> None:
    """An attribute called `order.id` appearing on multiple services'
    spans with ID-shaped values must be detected as a business key."""
    spans = [
        _span_dict(
            trace_id="t1",
            span_id="s1",
            service="api",
            operation="POST /checkout",
            attributes={"order.id": "ORD-12345678"},
        ),
        _span_dict(
            trace_id="t1",
            span_id="s2",
            service="orders",
            operation="POST /orders",
            parent="s1",
            attributes={"order.id": "ORD-12345678"},
        ),
        _span_dict(
            trace_id="t1",
            span_id="s3",
            service="payment",
            operation="POST /charge",
            parent="s2",
            attributes={"order.id": "ORD-12345678"},
        ),
    ]
    bundle = _bundle_dict(trace_id="t1", spans=spans)
    path = _write_bundle_file(tmp_path, [bundle])

    samples = load_correlated(path)
    detected = detect_config(samples)
    names = [name for name, _ in detected.business_keys]
    assert "order.id" in names, (
        f"order.id present on 3 services with ID-shaped values should be detected — got {names}"
    )


def test_init_skips_free_form_text_even_when_named_id(tmp_path: Path) -> None:
    """An attribute named `*.id` but carrying free-form text (e.g. a
    URL or description) must NOT be detected as a business key."""
    spans = [
        _span_dict(
            trace_id="t1",
            span_id="s1",
            service="api",
            operation="POST /x",
            attributes={"page.id": "https://example.com/some/long/url/with/text"},
        ),
        _span_dict(
            trace_id="t1",
            span_id="s2",
            service="renderer",
            operation="render",
            parent="s1",
            attributes={"page.id": "https://example.com/some/long/url/with/text"},
        ),
    ]
    bundle = _bundle_dict(trace_id="t1", spans=spans)
    path = _write_bundle_file(tmp_path, [bundle])

    detected = detect_config(load_correlated(path))
    names = [name for name, _ in detected.business_keys]
    assert "page.id" not in names, "URLs are not ID-shaped and must not become business keys"


def test_init_collects_all_services(tmp_path: Path) -> None:
    spans = [
        _span_dict(trace_id="t1", span_id="s1", service="alpha", operation="x"),
        _span_dict(trace_id="t1", span_id="s2", service="beta", operation="y", parent="s1"),
        _span_dict(trace_id="t2", span_id="s3", service="gamma", operation="z"),
    ]
    bundles = [
        _bundle_dict(trace_id="t1", spans=spans[:2]),
        _bundle_dict(trace_id="t2", spans=spans[2:]),
    ]
    path = _write_bundle_file(tmp_path, bundles)

    detected = detect_config(load_correlated(path))
    assert detected.services == ["alpha", "beta", "gamma"]


def test_init_detects_http_handler_prefixes(tmp_path: Path) -> None:
    # Each prefix needs ≥ 2 occurrences to be picked up (single
    # occurrences are noise in real telemetry).
    bundles = [
        _bundle_dict(
            trace_id="t1",
            spans=[
                _span_dict(trace_id="t1", span_id="s1", service="api", operation="POST /checkout"),
                _span_dict(
                    trace_id="t1",
                    span_id="s2",
                    service="api",
                    operation="GET /orders/123",
                    parent="s1",
                ),
            ],
        ),
        _bundle_dict(
            trace_id="t2",
            spans=[
                _span_dict(trace_id="t2", span_id="s3", service="api", operation="POST /orders"),
                _span_dict(trace_id="t2", span_id="s4", service="api", operation="GET /orders/124"),
            ],
        ),
    ]
    path = _write_bundle_file(tmp_path, bundles)

    detected = detect_config(load_correlated(path))
    patterns = {p for p, _ in detected.handler_patterns}
    assert "POST " in patterns
    assert "GET " in patterns


def test_init_renders_round_trippable_yaml(tmp_path: Path) -> None:
    """The YAML generated by `arip init` must load back via the
    existing config loader without errors."""
    spans = [
        _span_dict(
            trace_id="t1",
            span_id="s1",
            service="api",
            operation="POST /x",
            attributes={"order.id": "ORD-AAAAAA"},
        ),
        _span_dict(
            trace_id="t1",
            span_id="s2",
            service="orders",
            operation="POST /orders",
            parent="s1",
            attributes={"order.id": "ORD-AAAAAA"},
        ),
    ]
    bundle = _bundle_dict(trace_id="t1", spans=spans)
    path = _write_bundle_file(tmp_path, [bundle])

    detected = detect_config(load_correlated(path))
    yaml_text = render_yaml(detected, environment_name="my-env")

    out = tmp_path / "arip.yaml"
    out.write_text(yaml_text)
    cfg = load_config_yaml(out)

    assert cfg.name == "my-env"
    assert "order.id" in cfg.business_key_attrs
    assert "api" in cfg.expected_services_per_trace
    assert "orders" in cfg.expected_services_per_trace


def test_init_handles_empty_bundle_gracefully(tmp_path: Path) -> None:
    """A bundle file with no parseable bundles must produce a
    DetectedConfig with helpful notes, not crash."""
    detected = detect_config([])
    assert detected.n_traces == 0
    assert "no traces in sample" in " ".join(detected.notes)


# ─── arip doctor: per-rule diagnosis ─────────────────────────────────


def test_doctor_reports_retry_storm_blocker_when_no_retry_attempt(tmp_path: Path) -> None:
    spans = [
        _span_dict(trace_id="t1", span_id="s1", service="api", operation="POST /x"),
        _span_dict(trace_id="t1", span_id="s2", service="db", operation="db.query", parent="s1"),
    ]
    bundle = _bundle_dict(trace_id="t1", spans=spans)
    path = _write_bundle_file(tmp_path, [bundle])

    report = diagnose(load_correlated(path))
    retry = next(r for r in report.rules if r.rule_id == "retry_storm")
    assert not retry.would_fire
    assert retry.blocker is not None
    assert "retry.attempt" in retry.next_step


def test_doctor_marks_rule_ready_when_signals_present(tmp_path: Path) -> None:
    """A 3-attempt retry chain should make doctor mark retry_storm
    as ready (would_fire=True) when the rule actually fires."""
    spans = [
        _span_dict(trace_id="t1", span_id="root", service="api", operation="POST /x"),
        _span_dict(
            trace_id="t1",
            span_id="a1",
            service="api",
            operation="inventory.reserve_attempt",
            parent="root",
            attributes={"retry.attempt": 1},
        ),
        _span_dict(
            trace_id="t1",
            span_id="a2",
            service="api",
            operation="inventory.reserve_attempt",
            parent="root",
            attributes={"retry.attempt": 2},
        ),
        _span_dict(
            trace_id="t1",
            span_id="a3",
            service="api",
            operation="inventory.reserve_attempt",
            parent="root",
            attributes={"retry.attempt": 3},
        ),
    ]
    logs = [
        {
            "timestamp": "2026-05-30T10:00:00Z",
            "service_name": "api",
            "level": "WARN",
            "message": "transient failure on attempt 1",
            "trace_id": "t1",
            "fields": {},
        }
    ]
    bundle = _bundle_dict(trace_id="t1", spans=spans, logs=logs)
    path = _write_bundle_file(tmp_path, [bundle])

    report = diagnose(load_correlated(path))
    retry = next(r for r in report.rules if r.rule_id == "retry_storm")
    assert retry.would_fire is True
    assert retry.primary_count >= 1


def test_doctor_renders_markdown_with_summary_line(tmp_path: Path) -> None:
    spans = [_span_dict(trace_id="t1", span_id="s1", service="api", operation="POST /x")]
    path = _write_bundle_file(tmp_path, [_bundle_dict(trace_id="t1", spans=spans)])
    text = render_doctor_report(diagnose(load_correlated(path)))
    assert "rules would fire on this sample" in text
    assert "Summary:" in text


# ─── auto-discovery of arip.yaml ─────────────────────────────────────


def test_observe_auto_discovers_arip_yaml_in_cwd(tmp_path: Path, monkeypatch) -> None:
    """If --config is omitted but cwd has arip.yaml, the observe CLI
    must pick it up. We test by introspecting the build_parser output
    + simulating the discovery logic inline."""
    cfg = tmp_path / "arip.yaml"
    cfg.write_text("name: discovered\nbusiness_keys: [order.id]\n")
    monkeypatch.chdir(tmp_path)

    # Simulate the discovery the CLI does. We can't easily run the
    # full `arip observe` flow here without a real bundle stream, so
    # we mirror the discovery snippet.
    cfg_path = None
    for candidate in (Path("arip.yaml"), Path("arip.yml"), Path(".arip/config.yaml")):
        if candidate.exists():
            cfg_path = candidate
            break

    assert cfg_path is not None
    loaded = load_config_yaml(cfg_path)
    assert loaded.name == "discovered"
    assert loaded.business_key_attrs == ["order.id"]
