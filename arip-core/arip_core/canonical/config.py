"""NormalizationConfig — how raw telemetry maps to ARIP-canonical signals.

The defaults in this file match the ARIP demo stack's conventions
exactly, so existing scenarios + tests do not regress. A customer
points ARIP at their own telemetry by writing a YAML file that
overrides only the fields whose conventions differ:

    business_keys:        [account_id, tenant_id]
    retry:
      attempt_attr:       http.retry_count
      reason_attr:        http.retry.reason

If a field is omitted, the default is used. Empty list means
"feature disabled" — the corresponding rule will gracefully fail to
fire rather than guess against unknown telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NormalizationConfig:
    """Maps raw telemetry attribute names to ARIP-canonical signals.

    Every field has a default tuned to the ARIP demo stack. To onboard
    a new environment, override the fields whose names differ.
    """

    # ─── Business keys ───────────────────────────────────────────────
    # Attribute names that may carry the entity identifier on a span.
    # First match wins. Used for cross-trace correlation
    # (concurrent_modification rule). Empty list → cross-trace
    # correlation disabled.
    business_key_attrs: list[str] = field(default_factory=lambda: ["order.id"])

    # ─── Retry signal attributes ─────────────────────────────────────
    # If retry_attempt_attr is missing on a span, the retry_storm rule
    # treats the span as "no retry metadata" → does not fire.
    retry_attempt_attr: str = "retry.attempt"
    retry_max_attempts_attr: str = "retry.max_attempts"
    retry_backoff_attr: str = "retry.backoff_ms"
    retry_reason_attr: str = "retry.reason"
    retry_policy_attr: str = "retry.policy"

    # ─── DB signal attributes ────────────────────────────────────────
    # A span is "DB" if it has db_system_attr set OR its operation name
    # matches one of db_operation_patterns.
    db_system_attr: str = "db.system"
    db_operation_patterns: list[str] = field(default_factory=lambda: ["db."])

    # Pool stats — empty values mean "this environment doesn't emit
    # pool telemetry"; db_pool_exhaustion rule then naturally abstains.
    db_pool_acquired_attr: str = "db.pool.acquired"
    db_pool_max_attr: str = "db.pool.max"
    db_pool_wait_attr: str = "db.pool.wait_ms"
    db_pool_empty_acquires_attr: str = "db.pool.empty_acquires_total"

    # Operation name(s) that identify the connection-acquire span
    # specifically (used to phrase pool exhaustion evidence). Optional.
    db_acquire_operation_names: list[str] = field(
        default_factory=lambda: ["db.acquire_connection", "db.connection_hold"]
    )

    # ─── HTTP attributes ─────────────────────────────────────────────
    # In priority order. Used by downstream_error rule.
    http_status_attrs: list[str] = field(
        default_factory=lambda: ["http.response.status_code", "http.status_code"]
    )

    # ─── Handler-vs-DB latency identification ────────────────────────
    # An operation name is a "handler" if it contains any of these
    # substrings. Used by latency_vs_db rule.
    handler_operation_patterns: list[str] = field(default_factory=lambda: ["handle_"])

    # ─── State-transition events ─────────────────────────────────────
    # Used by concurrent_modification rule.
    state_transition_event_name: str = "state.transition"
    state_transition_from_attr: str = "state.from"
    state_transition_to_attr: str = "state.to"

    # ─── Source identifier ───────────────────────────────────────────
    # Optional label so reports can show which config was applied
    # (e.g. "demo", "production-eu", "tenant-foo").
    name: str = "default"

    # ─────────────────────────────────────────────────────────────────

    def signals_summary(self) -> dict[str, Any]:
        """Compact dict describing which canonical signals are enabled."""
        return {
            "name": self.name,
            "business_keys_configured": bool(self.business_key_attrs),
            "retry_signals_configured": bool(self.retry_attempt_attr),
            "db_pool_signals_configured": all(
                [
                    self.db_pool_acquired_attr,
                    self.db_pool_max_attr,
                ]
            ),
            "state_transitions_configured": bool(self.state_transition_event_name),
        }


def load_config_yaml(path: str | Path) -> NormalizationConfig:
    """Load a NormalizationConfig from a YAML file.

    Missing fields fall back to defaults. Unknown fields raise so
    that typos surface early.
    """
    import yaml  # local import — keeps yaml a soft dep at module level

    p = Path(path)
    data = yaml.safe_load(p.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{p}: top-level must be a mapping")

    return _config_from_dict(data, source_name=str(p.stem))


def _config_from_dict(data: dict[str, Any], source_name: str) -> NormalizationConfig:
    """Build a NormalizationConfig from a nested dict (YAML-friendly)."""
    cfg = NormalizationConfig(name=data.get("name", source_name))

    if "business_keys" in data:
        cfg.business_key_attrs = list(data["business_keys"])

    retry = data.get("retry") or {}
    cfg.retry_attempt_attr = retry.get("attempt_attr", cfg.retry_attempt_attr)
    cfg.retry_max_attempts_attr = retry.get("max_attempts_attr", cfg.retry_max_attempts_attr)
    cfg.retry_backoff_attr = retry.get("backoff_attr", cfg.retry_backoff_attr)
    cfg.retry_reason_attr = retry.get("reason_attr", cfg.retry_reason_attr)
    cfg.retry_policy_attr = retry.get("policy_attr", cfg.retry_policy_attr)

    db = data.get("db") or {}
    cfg.db_system_attr = db.get("system_attr", cfg.db_system_attr)
    cfg.db_operation_patterns = list(db.get("operation_patterns", cfg.db_operation_patterns))
    cfg.db_pool_acquired_attr = (db.get("pool") or {}).get(
        "acquired_attr", cfg.db_pool_acquired_attr
    )
    cfg.db_pool_max_attr = (db.get("pool") or {}).get("max_attr", cfg.db_pool_max_attr)
    cfg.db_pool_wait_attr = (db.get("pool") or {}).get("wait_ms_attr", cfg.db_pool_wait_attr)
    cfg.db_pool_empty_acquires_attr = (db.get("pool") or {}).get(
        "empty_acquires_attr", cfg.db_pool_empty_acquires_attr
    )
    cfg.db_acquire_operation_names = list(
        (db.get("pool") or {}).get("acquire_operation_names", cfg.db_acquire_operation_names)
    )

    if "http_status_attrs" in data:
        cfg.http_status_attrs = list(data["http_status_attrs"])

    if "handler_operation_patterns" in data:
        cfg.handler_operation_patterns = list(data["handler_operation_patterns"])

    state = data.get("state_transitions") or {}
    cfg.state_transition_event_name = state.get("event_name", cfg.state_transition_event_name)
    cfg.state_transition_from_attr = state.get("from_attr", cfg.state_transition_from_attr)
    cfg.state_transition_to_attr = state.get("to_attr", cfg.state_transition_to_attr)

    known_top_level = {
        "name",
        "business_keys",
        "retry",
        "db",
        "http_status_attrs",
        "handler_operation_patterns",
        "state_transitions",
    }
    unknown = set(data) - known_top_level
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")

    return cfg
