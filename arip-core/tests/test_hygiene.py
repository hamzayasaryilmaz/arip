"""Tests for telemetry hygiene findings.

Hygiene findings are operator-facing — they don't change engine
reasoning but DO tell the operator what telemetry would let more
rules fire or what coverage gap to close.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arip_core.canonical.config import NormalizationConfig
from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, LogEntry, Span
from arip_core.quality.hygiene import collect_hygiene_findings

NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _span(*, span_id="s", parent=None, service="svc", op="op", attrs=None) -> Span:
    return Span(
        trace_id="t",
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        operation_name=op,
        start_time=NOW,
        duration_us=1000,
        status="OK",
        status_message="",
        attributes=attrs or {},
        events=[],
    )


def _ct(
    spans: list[Span],
    *,
    logs: list[LogEntry] | None = None,
    config: NormalizationConfig | None = None,
) -> CorrelatedTelemetry:
    return CorrelatedTelemetry(
        failure=FailureEvent(
            test_name="t",
            timestamp=NOW,
            environment="test",
            trace_id="t",
            assertion="",
            error_message="",
        ),
        logs=logs or [],
        spans=spans,
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="t",
        related_trace_ids=[],
        order_id=None,
        normalization_config=config or NormalizationConfig(),
    )


# ---------- span-tree gap detection ------------------------------


def test_no_findings_when_tree_is_complete() -> None:
    spans = [
        _span(span_id="root"),
        _span(span_id="child", parent="root"),
    ]
    findings = collect_hygiene_findings(_ct(spans), NormalizationConfig())
    assert findings == []


def test_finds_orphan_spans_grouped_by_service() -> None:
    spans = [
        _span(span_id="o1", parent="missing-1", service="svc-a"),
        _span(span_id="o2", parent="missing-2", service="svc-a"),
        _span(span_id="o3", parent="missing-3", service="svc-b"),
    ]
    findings = collect_hygiene_findings(_ct(spans), NormalizationConfig())
    assert len(findings) == 1
    f = findings[0]
    assert "orphan span(s)" in f
    assert "svc-a (2)" in f
    assert "svc-b (1)" in f
    assert "API gateway" in f  # the actionable hint


# ---------- service-coverage assertion ---------------------------


def test_no_finding_when_no_expected_services_configured() -> None:
    """Default config has no expected_services — check is no-op."""
    spans = [_span(span_id="s", service="frontend")]
    cfg = NormalizationConfig()
    assert cfg.expected_services_per_trace == []
    findings = collect_hygiene_findings(_ct(spans), cfg)
    # Other checks might emit (orphan), but service-coverage shouldn't
    assert not any("Service-coverage gap" in f for f in findings)


def test_finds_missing_expected_service() -> None:
    cfg = NormalizationConfig(expected_services_per_trace=["frontend", "cart", "payment"])
    spans = [
        _span(span_id="a", service="frontend"),
        _span(span_id="b", parent="a", service="cart"),
        # payment missing
    ]
    findings = collect_hygiene_findings(_ct(spans), cfg)
    coverage_findings = [f for f in findings if "Service-coverage gap" in f]
    assert len(coverage_findings) == 1
    assert "['payment']" in coverage_findings[0]


def test_no_coverage_finding_when_all_expected_present() -> None:
    cfg = NormalizationConfig(expected_services_per_trace=["frontend", "cart"])
    spans = [
        _span(span_id="a", service="frontend"),
        _span(span_id="b", parent="a", service="cart"),
    ]
    findings = collect_hygiene_findings(_ct(spans), cfg)
    assert not any("Service-coverage gap" in f for f in findings)


# ---------- log-source completeness ------------------------------


def test_finds_complete_log_source_absence() -> None:
    """expected_log_sources configured but zero logs in bundle."""
    cfg = NormalizationConfig(expected_log_sources=["frontend", "payment"])
    spans = [
        _span(span_id="a", service="frontend"),
        _span(span_id="b", parent="a", service="payment"),
    ]
    findings = collect_hygiene_findings(_ct(spans, logs=[]), cfg)
    log_findings = [f for f in findings if "Log-source gap" in f]
    assert len(log_findings) == 1
    assert "0 log entries" in log_findings[0]


def test_finds_partial_log_source_coverage() -> None:
    """Some expected log sources present, others missing."""
    cfg = NormalizationConfig(expected_log_sources=["frontend", "payment"])
    spans = [
        _span(span_id="a", service="frontend"),
        _span(span_id="b", parent="a", service="payment"),
    ]
    logs = [
        LogEntry(
            timestamp=NOW,
            service_name="frontend",
            level="INFO",
            message="hello",
            trace_id="t",
            fields={},
        ),
    ]
    findings = collect_hygiene_findings(_ct(spans, logs=logs), cfg)
    log_findings = [f for f in findings if "Log-source gap" in f]
    assert len(log_findings) == 1
    assert "['payment']" in log_findings[0]
    assert "Missing" in log_findings[0]


# ---------- business-key propagation -----------------------------


def test_finds_business_key_not_propagated() -> None:
    """Entry-point has business_key but downstream span doesn't.
    Cross-trace correlation by this key won't work for this request."""
    spans = [
        _span(span_id="root", service="frontend", attrs={"order.id": "ORD-1"}),
        _span(span_id="child", parent="root", service="payment", attrs={}),
    ]
    findings = collect_hygiene_findings(_ct(spans), NormalizationConfig())
    propagation = [f for f in findings if "Business-key propagation gap" in f]
    assert len(propagation) == 1


def test_no_finding_when_business_key_propagates() -> None:
    spans = [
        _span(span_id="root", service="frontend", attrs={"order.id": "ORD-1"}),
        _span(span_id="child", parent="root", service="payment", attrs={"order.id": "ORD-1"}),
    ]
    findings = collect_hygiene_findings(_ct(spans), NormalizationConfig())
    assert not any("Business-key propagation gap" in f for f in findings)


def test_business_key_aliases_treated_as_propagation() -> None:
    """If operator declared `order.id` → `payment.order_ref` alias,
    downstream span carrying `payment.order_ref` counts as propagation."""
    cfg = NormalizationConfig(business_key_aliases={"order.id": ["payment.order_ref"]})
    spans = [
        _span(span_id="root", service="frontend", attrs={"order.id": "ORD-1"}),
        _span(
            span_id="child", parent="root", service="payment", attrs={"payment.order_ref": "ORD-1"}
        ),  # alias
    ]
    findings = collect_hygiene_findings(_ct(spans, config=cfg), cfg)
    assert not any("Business-key propagation gap" in f for f in findings)


def test_no_finding_when_no_business_key_configured() -> None:
    """If business_key_attrs is empty, the propagation check no-ops."""
    cfg = NormalizationConfig(business_key_attrs=[])
    spans = [_span(span_id="root", service="frontend")]
    findings = collect_hygiene_findings(_ct(spans, config=cfg), cfg)
    assert not any("Business-key propagation gap" in f for f in findings)


# ---------- abstention next_step hints ---------------------------


def test_abstention_includes_next_step() -> None:
    """Every abstention code has a templated next-step hint."""
    from arip_core.engine.abstention import AbstentionReason

    for code in [
        "no_primary_trace",
        "empty_telemetry",
        "no_rule_matched",
        "weak_evidence",
        "conflicting_hypotheses",
    ]:
        r = AbstentionReason(code=code, headline="h", detail="d")
        assert r.next_step
        assert len(r.next_step) > 50  # not a stub


# ---------- canonical signals alias broadening -------------------


def test_signals_returns_aliased_business_key_value() -> None:
    """Signals.business_key_for picks up aliased attribute values."""
    cfg = NormalizationConfig(
        business_key_attrs=["order.id"],
        business_key_aliases={"order.id": ["payment.order_ref"]},
    )
    from arip_core.canonical.signals import Signals

    sig = Signals(cfg)
    s = _span(attrs={"payment.order_ref": "ORD-99"})
    assert sig.business_key_for(s) == "ORD-99"


def test_signals_all_business_key_attrs_includes_aliases() -> None:
    cfg = NormalizationConfig(
        business_key_attrs=["order.id", "account.id"],
        business_key_aliases={
            "order.id": ["payment.order_ref"],
            "account.id": ["billing.acc_no"],
        },
    )
    from arip_core.canonical.signals import Signals

    sig = Signals(cfg)
    attrs = sig.all_business_key_attrs()
    assert "order.id" in attrs
    assert "payment.order_ref" in attrs
    assert "account.id" in attrs
    assert "billing.acc_no" in attrs
