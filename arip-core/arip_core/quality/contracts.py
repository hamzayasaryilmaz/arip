"""Per-rule telemetry contracts.

What each shipped rule MUST see in order to fire and what it COULD see
to lift confidence. The contract is declarative so the CLI's preflight
can report "your telemetry is missing X — rule Y will silently no-op"
without us hardcoding rule semantics in two places.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleContract:
    rule_id: str
    description: str
    required_signals: tuple[str, ...]
    optional_signals: tuple[str, ...]
    fires_on_abstain: str  # what the rule does when required signals are missing


# Canonical signal names — these are the names of *Signals* methods, not
# raw attribute names. The raw attribute mapping is in NormalizationConfig.
RULE_CONTRACTS: tuple[RuleContract, ...] = (
    RuleContract(
        rule_id="concurrent_modification",
        description="Two operations mutating the same business entity overlapping in time",
        required_signals=(
            "business_keys",  # business_key_attrs must be non-empty
            "state_transitions",  # state_transition events must be configured
        ),
        optional_signals=(
            "warn_logs",  # WARN log corroboration (+0.12 confidence)
        ),
        fires_on_abstain="returns [] silently — engine sees no rule match",
    ),
    RuleContract(
        rule_id="retry_storm",
        description="2+ same-operation retries in a single trace",
        required_signals=(
            "retry_attempt",  # retry.attempt attribute present on retry spans
        ),
        optional_signals=(
            "retry_reason",  # consistent reason → +0.05
            "retry_backoff_ms",  # detect exponential pattern → +0.04
            "retry_max_attempts",  # detect exhaustion → +0.03
            "error_logs",  # ERROR-level log corroboration → +0.02
        ),
        fires_on_abstain="returns [] silently if no retry.attempt present anywhere",
    ),
    RuleContract(
        rule_id="downstream_error",
        description="ERROR-status chain crossing a service boundary",
        required_signals=(
            "span_error_status",  # span.is_error must be set by instrumentation
            "service_boundary",  # spans must carry service_name across services
        ),
        optional_signals=(
            "http_status",  # phrases evidence as 'HTTP 503' etc.
            "error_logs",  # corroborating evidence
        ),
        fires_on_abstain="returns [] silently if no cross-service ERROR chain exists",
    ),
    RuleContract(
        rule_id="db_pool_exhaustion",
        description="DB connection pool saturated — latency in acquire, not query",
        required_signals=(
            "db_pool_stats",  # db.pool.acquired AND db.pool.max AND db.pool.wait_ms
        ),
        optional_signals=(
            "db_query_span",  # contrasting healthy-query span → +0.05
            "warn_logs",  # WARN log corroboration → +0.05
            "empty_acquires_total",  # proves pool actually ran dry → +0.03
        ),
        fires_on_abstain=(
            "returns [] silently if no span carries db.pool.* attributes — "
            "DELIBERATELY strict to avoid false-positives on slow queries"
        ),
    ),
    RuleContract(
        rule_id="latency_vs_db",
        description="Application-layer latency above the DB layer",
        required_signals=(
            "handler_span_identifiable",  # operation name matches handler pattern
            "db_child_span",  # at least one db.* child span with duration
        ),
        optional_signals=(),
        fires_on_abstain="returns [] silently if no handler/DB child relationship found",
    ),
)


def contracts_for_rule(rule_id: str) -> RuleContract | None:
    for c in RULE_CONTRACTS:
        if c.rule_id == rule_id:
            return c
    return None
