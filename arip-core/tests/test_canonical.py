"""Tests for the canonical normalization layer.

What this proves:

  1. The Signals accessor reads canonical signals through configured
     attribute names — swap the config and the same span produces
     different canonical values.
  2. The YAML loader reads a customer-style config file and produces a
     NormalizationConfig that the rules can consume.
  3. The same rule that fires on demo telemetry ALSO fires on
     foreign-convention telemetry when the convention is mapped via
     config — i.e. rules are decoupled from raw attribute names.
  4. Graceful degradation: when business_keys is empty, the
     concurrent_modification rule no-ops cleanly rather than crashing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arip_core.canonical.config import NormalizationConfig, _config_from_dict, load_config_yaml
from arip_core.canonical.signals import Signals
from arip_core.collector.failure_event import FailureEvent
from arip_core.correlator.models import CorrelatedTelemetry, Span
from arip_core.engine.rules.retry_storm import RetryStormRule
from arip_core.engine.rules.webhook_race import WebhookRaceRule

NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)


def _ct(spans, config=None):
    return CorrelatedTelemetry(
        failure=FailureEvent(
            test_name="t",
            timestamp=NOW,
            environment="test",
            trace_id="tp",
            assertion="x",
            error_message="boom",
        ),
        logs=[],
        spans=spans,
        k8s_events=[],
        db_queries=[],
        timeline=[],
        primary_trace_id="tp",
        normalization_config=config or NormalizationConfig(),
    )


def _span(
    *,
    op,
    service="payment-service",
    span_id="s",
    parent=None,
    duration_us=1_000,
    status="OK",
    attrs=None,
    events=None,
    trace_id="tp",
    start_ms=0,
):
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        service_name=service,
        operation_name=op,
        start_time=NOW + timedelta(milliseconds=start_ms),
        duration_us=duration_us,
        status=status,
        status_message="",
        attributes=attrs or {},
        events=events or [],
    )


# --- Signals accessor -------------------------------------------------


def test_signals_business_key_uses_configured_attrs_in_priority_order():
    cfg = NormalizationConfig(business_key_attrs=["account.id", "tenant.id"])
    sig = Signals(cfg)
    s = _span(op="x", attrs={"tenant.id": "T-42"})
    assert sig.business_key_for(s) == "T-42"
    s2 = _span(op="x", attrs={"account.id": "A-1", "tenant.id": "T-9"})
    # First-match-wins by config order
    assert sig.business_key_for(s2) == "A-1"


def test_signals_business_key_returns_none_when_unknown():
    sig = Signals(NormalizationConfig())
    s = _span(op="x", attrs={"nope.id": "x"})
    assert sig.business_key_for(s) is None


def test_signals_retry_attempt_typed_int():
    cfg = NormalizationConfig(retry_attempt_attr="http.retry.attempt_number")
    sig = Signals(cfg)
    s = _span(op="x", attrs={"http.retry.attempt_number": "3"})  # str
    assert sig.retry_attempt(s) == 3


def test_signals_retry_attempt_none_when_absent():
    sig = Signals(NormalizationConfig())
    s = _span(op="x", attrs={})
    assert sig.retry_attempt(s) is None


def test_signals_pool_stats_returns_none_when_no_pool_attrs():
    sig = Signals(NormalizationConfig())
    s = _span(op="db.x", attrs={"db.system": "postgresql"})
    assert sig.pool_stats(s) is None


def test_signals_pool_stats_at_capacity_computed():
    sig = Signals(NormalizationConfig())
    s = _span(
        op="db.acquire_connection",
        attrs={
            "db.system": "postgresql",
            "db.pool.acquired": 3,
            "db.pool.max": 3,
            "db.pool.wait_ms": 1500,
        },
    )
    stats = sig.pool_stats(s)
    assert stats is not None
    assert stats.at_capacity is True
    assert stats.wait_ms == 1500


def test_signals_is_db_span_via_system_attr():
    sig = Signals(NormalizationConfig())
    s = _span(op="checkout", attrs={"db.system": "postgresql"})
    assert sig.is_db_span(s) is True


def test_signals_is_db_span_via_operation_pattern():
    cfg = NormalizationConfig(db_operation_patterns=["sql.", "data."])
    sig = Signals(cfg)
    s = _span(op="sql.select", attrs={})
    assert sig.is_db_span(s) is True
    s2 = _span(op="checkout.process", attrs={})
    assert sig.is_db_span(s2) is False


def test_signals_state_transitions_uses_configured_event_name():
    cfg = NormalizationConfig(
        state_transition_event_name="domain.event.state_changed",
        state_transition_from_attr="domain.from_state",
        state_transition_to_attr="domain.to_state",
        business_key_attrs=["entity.id"],
    )
    sig = Signals(cfg)
    s = _span(
        op="x",
        attrs={"entity.id": "E-1"},
        events=[
            {
                "timestamp": NOW,
                "fields": {
                    "event": "domain.event.state_changed",
                    "domain.from_state": "pending",
                    "domain.to_state": "confirmed",
                },
            }
        ],
    )
    transitions = sig.state_transitions(s)
    assert len(transitions) == 1
    assert transitions[0].from_state == "pending"
    assert transitions[0].to_state == "confirmed"
    assert transitions[0].entity_id == "E-1"


# --- YAML loader -----------------------------------------------------


def test_config_from_dict_applies_overrides():
    data = {
        "name": "foo",
        "business_keys": ["account.id"],
        "retry": {"attempt_attr": "x.attempt"},
    }
    cfg = _config_from_dict(data, source_name="foo")
    assert cfg.name == "foo"
    assert cfg.business_key_attrs == ["account.id"]
    assert cfg.retry_attempt_attr == "x.attempt"
    # Untouched defaults preserved
    assert cfg.retry_max_attempts_attr == "retry.max_attempts"


def test_config_from_dict_rejects_unknown_keys():
    with pytest.raises(ValueError):
        _config_from_dict({"unrecognised_key": True}, source_name="x")


def test_load_config_yaml_demo_file():
    """Demo YAML must load and equal the default config (modulo `name`)."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_config_yaml(repo_root / "arip-core" / "configs" / "demo.yaml")
    default = NormalizationConfig()
    assert cfg.business_key_attrs == default.business_key_attrs
    assert cfg.retry_attempt_attr == default.retry_attempt_attr
    assert cfg.db_system_attr == default.db_system_attr
    assert cfg.state_transition_event_name == default.state_transition_event_name


def test_load_config_yaml_foreign_file():
    """Foreign YAML must override the expected fields."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_config_yaml(repo_root / "arip-core" / "configs" / "foreign-conventions.yaml")
    assert "tenant.id" in cfg.business_key_attrs
    assert cfg.retry_attempt_attr == "http.retry.attempt_number"
    assert "Controller#" in cfg.handler_operation_patterns
    assert cfg.state_transition_event_name == "domain.event.state_changed"


# --- Rules are decoupled from raw attribute names --------------------


def test_retry_storm_fires_with_foreign_attribute_names():
    """The same retry storm pattern under a foreign convention must
    fire the same rule, with no rule-side changes."""
    cfg = NormalizationConfig(
        retry_attempt_attr="http.retry.attempt_number",
        retry_max_attempts_attr="http.retry.max",
        retry_backoff_attr="http.retry.backoff.delay_ms",
        retry_reason_attr="http.retry.cause",
        retry_policy_attr="http.retry.policy",
    )
    spans = [
        _span(
            op="orders.reserve.attempt",
            span_id=f"a{n}",
            status="ERROR",
            attrs={
                "http.retry.attempt_number": n,
                "http.retry.max": 5,
                "http.retry.backoff.delay_ms": [0, 50, 100][n - 1],
                "http.retry.policy": "exponential",
                "http.retry.cause": "upstream 503",
            },
        )
        for n in (1, 2, 3)
    ]
    out = RetryStormRule().evaluate(_ct(spans, config=cfg))
    assert len(out) == 1
    h = out[0]
    assert h.rule_id == "retry_storm"
    assert "3 attempts" in h.title


def test_concurrent_modification_fires_with_foreign_business_key():
    """Cross-trace correlation must work via the configured business
    key attribute name."""
    cfg = NormalizationConfig(
        business_key_attrs=["tenant.id"],
        state_transition_event_name="state.transition",
        state_transition_from_attr="state.from",
        state_transition_to_attr="state.to",
    )
    outer = _span(
        op="checkout.process",
        trace_id="t-co",
        span_id="co",
        start_ms=0,
        duration_us=300_000,
        attrs={"tenant.id": "T-1"},
        events=[
            {
                "timestamp": NOW,
                "fields": {"event": "state.transition", "state.from": "", "state.to": "pending"},
            },
            {
                "timestamp": NOW + timedelta(milliseconds=300),
                "fields": {
                    "event": "state.transition",
                    "state.from": "pending",
                    "state.to": "confirmed",
                },
            },
        ],
    )
    inner = _span(
        op="webhook.process",
        trace_id="t-wh",
        span_id="wh",
        start_ms=50,
        duration_us=1_000,
        attrs={"tenant.id": "T-1"},
        events=[
            {
                "timestamp": NOW + timedelta(milliseconds=50),
                "fields": {
                    "event": "state.transition",
                    "state.from": "pending",
                    "state.to": "paid",
                },
            }
        ],
    )
    out = WebhookRaceRule().evaluate(_ct([outer, inner], config=cfg))
    assert len(out) == 1
    assert out[0].rule_id == "concurrent_modification"


def test_concurrent_modification_no_ops_when_business_keys_disabled():
    """If the customer's config has no business keys configured, the
    cross-trace correlation rule must silently no-op, not crash."""
    cfg = NormalizationConfig(business_key_attrs=[])
    outer = _span(
        op="checkout.process",
        trace_id="t-co",
        span_id="co",
        start_ms=0,
        duration_us=300_000,
        attrs={"order.id": "ORD-1"},
    )
    out = WebhookRaceRule().evaluate(_ct([outer], config=cfg))
    assert out == []


def test_ct_signals_property_returns_signals_bound_to_config():
    cfg = NormalizationConfig(name="x", business_key_attrs=["x.id"])
    ct = _ct([], config=cfg)
    assert ct.signals.config is cfg
    assert ct.normalization_config is cfg


def test_signals_summary_reflects_disabled_features():
    cfg = NormalizationConfig(
        business_key_attrs=[],
        db_pool_acquired_attr="",
    )
    summary = cfg.signals_summary()
    assert summary["business_keys_configured"] is False
    assert summary["db_pool_signals_configured"] is False
