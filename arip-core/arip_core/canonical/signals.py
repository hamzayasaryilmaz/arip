"""Config-aware accessors over raw telemetry.

Every rule reads canonical signals through this layer. The mapping
from raw attribute names is driven by :class:`NormalizationConfig`;
swap the config and the same rules apply to a different telemetry
stack without code changes.

Missing signals return ``None`` (or ``[]`` for collections). This is
the graceful-degradation contract — a rule that needs ``retry.attempt``
on a stack that does not emit it will naturally not fire, not crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..correlator.models import Span
    from .config import NormalizationConfig


@dataclass
class StateTransition:
    """Canonical view of a single state-transition span event."""

    timestamp: datetime
    span_id: str
    service: str
    trace_id: str
    from_state: str | None
    to_state: str | None
    entity_id: str | None  # the business key value on the parent span


@dataclass
class PoolStats:
    """Canonical pool-saturation snapshot."""

    acquired: int | None
    max_size: int | None
    wait_ms: int | None
    empty_acquires_total: int | None

    @property
    def at_capacity(self) -> bool:
        return (
            self.acquired is not None
            and self.max_size is not None
            and self.max_size > 0
            and self.acquired >= self.max_size
        )


class Signals:
    """Read canonical signals from raw spans + logs using a config."""

    def __init__(self, config: "NormalizationConfig") -> None:
        self.config = config

    # ─── Business key ────────────────────────────────────────────────

    def business_key_for(self, span: "Span") -> str | None:
        """Return the business-key value (e.g. order_id) on this span,
        searching the configured attribute names in priority order."""
        for attr in self.config.business_key_attrs:
            v = span.attributes.get(attr)
            if v is not None:
                return str(v)
        return None

    def business_keys_enabled(self) -> bool:
        return bool(self.config.business_key_attrs)

    # ─── Retry signals ───────────────────────────────────────────────

    def retry_attempt(self, span: "Span") -> int | None:
        return _as_int(span.attributes.get(self.config.retry_attempt_attr))

    def retry_max_attempts(self, span: "Span") -> int | None:
        return _as_int(span.attributes.get(self.config.retry_max_attempts_attr))

    def retry_backoff_ms(self, span: "Span") -> int | None:
        return _as_int(span.attributes.get(self.config.retry_backoff_attr))

    def retry_reason(self, span: "Span") -> str | None:
        v = span.attributes.get(self.config.retry_reason_attr)
        return str(v) if v is not None else None

    def retry_policy(self, span: "Span") -> str | None:
        v = span.attributes.get(self.config.retry_policy_attr)
        return str(v) if v is not None else None

    # ─── DB signals ──────────────────────────────────────────────────

    def is_db_span(self, span: "Span") -> bool:
        if self.config.db_system_attr in span.attributes:
            return True
        op = span.operation_name
        for pattern in self.config.db_operation_patterns:
            if pattern and pattern in op:
                return True
        return False

    def is_db_acquire_span(self, span: "Span") -> bool:
        return span.operation_name in self.config.db_acquire_operation_names

    def pool_stats(self, span: "Span") -> PoolStats | None:
        """Return canonical PoolStats if this span carries any pool
        attribute, otherwise None."""
        a = span.attributes
        has_any = any(
            attr and attr in a
            for attr in (
                self.config.db_pool_acquired_attr,
                self.config.db_pool_max_attr,
                self.config.db_pool_wait_attr,
                self.config.db_pool_empty_acquires_attr,
            )
        )
        if not has_any:
            return None
        return PoolStats(
            acquired=_as_int(a.get(self.config.db_pool_acquired_attr)),
            max_size=_as_int(a.get(self.config.db_pool_max_attr)),
            wait_ms=_as_int(a.get(self.config.db_pool_wait_attr)),
            empty_acquires_total=_as_int(a.get(self.config.db_pool_empty_acquires_attr)),
        )

    def pool_signals_enabled(self) -> bool:
        return all([self.config.db_pool_acquired_attr, self.config.db_pool_max_attr])

    # ─── HTTP signals ────────────────────────────────────────────────

    def http_status(self, span: "Span") -> int | None:
        for attr in self.config.http_status_attrs:
            v = _as_int(span.attributes.get(attr))
            if v is not None:
                return v
        return None

    # ─── Handler identification ──────────────────────────────────────

    def is_handler_span(self, span: "Span") -> bool:
        op = span.operation_name
        return any(p and p in op for p in self.config.handler_operation_patterns)

    # ─── State transitions ───────────────────────────────────────────

    def state_transitions(self, span: "Span") -> list[StateTransition]:
        """Return all state-transition events on this span as canonical
        StateTransition records."""
        if not self.config.state_transition_event_name:
            return []
        out: list[StateTransition] = []
        entity = self.business_key_for(span)
        for ev in span.events:
            fields = ev.get("fields", {}) or {}
            if fields.get("event") != self.config.state_transition_event_name:
                continue
            ts = ev.get("timestamp")
            if not isinstance(ts, datetime):
                continue
            out.append(
                StateTransition(
                    timestamp=ts,
                    span_id=span.span_id,
                    service=span.service_name,
                    trace_id=span.trace_id,
                    from_state=_as_str(fields.get(self.config.state_transition_from_attr)),
                    to_state=_as_str(fields.get(self.config.state_transition_to_attr)),
                    # entity_id on the event takes precedence (when both are present)
                    entity_id=_as_str(
                        fields.get(self.config.business_key_attrs[0])
                        if self.config.business_key_attrs else None
                    ) or entity,
                )
            )
        return out


# ─── helpers ─────────────────────────────────────────────────────────


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _as_str(v: Any) -> str | None:
    return str(v) if v is not None else None
