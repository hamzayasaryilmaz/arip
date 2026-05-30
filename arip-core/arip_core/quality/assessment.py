"""Telemetry quality scoring.

Given a CorrelatedTelemetry, compute a score in ``[0.0, 1.0]`` that
reflects how trustworthy the input is for investigation purposes.
Reports surface the score so an engineer knows whether the engine's
output is operating on rich or thin signals.

This module never changes rule behaviour. A low quality score does
not force abstention — abstention is the engine's job. The score is
purely diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..correlator.models import CorrelatedTelemetry

# Confidence-band thresholds. Tunable but conservative.
LOW_CONFIDENCE_CEILING = 0.50
HIGH_CONFIDENCE_FLOOR = 0.80


@dataclass(frozen=True)
class SignalCoverage:
    """Coverage of a single canonical signal across the telemetry.

    ``ratio`` is "applicable observations satisfying the contract" /
    "applicable observations seen at all". A signal that does not
    apply to this trace (e.g. retry metadata when there are no retry
    spans) yields ``applicable == 0`` and is excluded from the score.
    """

    signal: str
    applicable: int
    satisfied: int
    note: str = ""

    @property
    def ratio(self) -> float:
        return self.satisfied / self.applicable if self.applicable else 1.0

    @property
    def is_applicable(self) -> bool:
        return self.applicable > 0


@dataclass(frozen=True)
class QualityFinding:
    """A human-readable note about a coverage gap."""

    signal: str
    severity: str  # 'info' | 'warn' | 'critical'
    message: str
    affected_count: int


@dataclass
class QualityAssessment:
    """Diagnostic snapshot of telemetry quality."""

    score: float
    confidence_band: str
    coverages: list[SignalCoverage] = field(default_factory=list)
    findings: list[QualityFinding] = field(default_factory=list)
    rules_likely_to_fire: list[str] = field(default_factory=list)
    rules_will_not_fire: list[str] = field(default_factory=list)

    @property
    def is_low_confidence(self) -> bool:
        return self.score < LOW_CONFIDENCE_CEILING

    @property
    def is_high_confidence(self) -> bool:
        return self.score >= HIGH_CONFIDENCE_FLOOR


def assess(ct: CorrelatedTelemetry) -> QualityAssessment:
    """Compute a quality assessment for the given telemetry.

    The score is the average ratio across applicable canonical
    coverages. Signals not applicable to this telemetry (e.g. retry
    metadata in a single-attempt trace) do not penalise the score —
    they are reported but excluded from the average.
    """
    signals = ct.signals
    coverages: list[SignalCoverage] = []
    findings: list[QualityFinding] = []

    # ── Trace presence ──────────────────────────────────────────────
    has_primary = any(s.trace_id == ct.primary_trace_id for s in ct.spans)
    coverages.append(
        SignalCoverage(
            signal="primary_trace_present",
            applicable=1,
            satisfied=1 if has_primary else 0,
            note="trace_id from FailureEvent resolves to spans in Jaeger",
        )
    )
    if not has_primary:
        findings.append(
            QualityFinding(
                signal="primary_trace_present",
                severity="critical",
                message="Primary trace not in telemetry backend (sampled/lost/unflushed). "
                "No rule can be evidence-grounded.",
                affected_count=1,
            )
        )

    # ── Propagation health ──────────────────────────────────────────
    span_ids = {s.span_id for s in ct.spans}
    non_root = [s for s in ct.spans if s.parent_span_id]
    orphans = [s for s in non_root if s.parent_span_id not in span_ids]
    if non_root:
        coverages.append(
            SignalCoverage(
                signal="propagation_health",
                applicable=len(non_root),
                satisfied=len(non_root) - len(orphans),
                note="non-root spans whose parent_span_id resolves",
            )
        )
        if orphans:
            findings.append(
                QualityFinding(
                    signal="propagation_health",
                    severity="warn",
                    message=f"{len(orphans)} span(s) are orphaned (parent_span_id "
                    f"references a span that is not in this telemetry slice). "
                    f"Cross-service walks may produce partial chains.",
                    affected_count=len(orphans),
                )
            )

    # ── Span error-status consistency ───────────────────────────────
    # When an HTTP status ≥ 400 is set, the span should also be ERROR.
    http_errors_seen = 0
    http_errors_with_error_status = 0
    for s in ct.spans:
        status = signals.http_status(s)
        if status is not None and status >= 400:
            http_errors_seen += 1
            if s.is_error:
                http_errors_with_error_status += 1
    if http_errors_seen:
        coverages.append(
            SignalCoverage(
                signal="error_status_consistency",
                applicable=http_errors_seen,
                satisfied=http_errors_with_error_status,
                note="HTTP-4xx/5xx spans also have OTel ERROR status",
            )
        )
        gap = http_errors_seen - http_errors_with_error_status
        if gap:
            findings.append(
                QualityFinding(
                    signal="error_status_consistency",
                    severity="warn",
                    message=f"{gap} HTTP-error span(s) lack OTel ERROR status. "
                    f"downstream_error walks may miss this chain.",
                    affected_count=gap,
                )
            )

    # ── Business key coverage on entry-point spans ──────────────────
    if signals.business_keys_enabled():
        entry_spans = _likely_entry_spans(ct.spans)
        if entry_spans:
            with_key = [s for s in entry_spans if signals.business_key_for(s)]
            coverages.append(
                SignalCoverage(
                    signal="business_key_on_entry",
                    applicable=len(entry_spans),
                    satisfied=len(with_key),
                    note="entry-point spans tagged with a configured business key",
                )
            )
            if len(with_key) < len(entry_spans):
                missing = len(entry_spans) - len(with_key)
                findings.append(
                    QualityFinding(
                        signal="business_key_on_entry",
                        severity="warn",
                        message=f"{missing} entry-point span(s) lack a business key. "
                        f"Cross-trace correlation for those requests is impossible.",
                        affected_count=missing,
                    )
                )

    # ── Retry metadata completeness ─────────────────────────────────
    retry_spans = [s for s in ct.spans if signals.retry_attempt(s) is not None]
    if retry_spans:
        # When retry.attempt is present, the FULL retry contract should be too.
        complete = [
            s
            for s in retry_spans
            if signals.retry_max_attempts(s) is not None
            and signals.retry_backoff_ms(s) is not None
            and signals.retry_policy(s) is not None
        ]
        coverages.append(
            SignalCoverage(
                signal="retry_metadata_completeness",
                applicable=len(retry_spans),
                satisfied=len(complete),
                note="retry spans carrying max_attempts + backoff_ms + policy",
            )
        )
        if len(complete) < len(retry_spans):
            findings.append(
                QualityFinding(
                    signal="retry_metadata_completeness",
                    severity="info",
                    message=f"{len(retry_spans) - len(complete)} retry span(s) are missing "
                    f"max_attempts / backoff / policy. retry_storm rule "
                    f"will fire but may not boost confidence past the baseline.",
                    affected_count=len(retry_spans) - len(complete),
                )
            )

    # ── Log → trace correlation ─────────────────────────────────────
    if ct.logs:
        correlated_logs = [l for l in ct.logs if l.trace_id]
        coverages.append(
            SignalCoverage(
                signal="log_trace_correlation",
                applicable=len(ct.logs),
                satisfied=len(correlated_logs),
                note="log entries carrying trace_id",
            )
        )
        gap = len(ct.logs) - len(correlated_logs)
        if gap:
            findings.append(
                QualityFinding(
                    signal="log_trace_correlation",
                    severity="warn",
                    message=f"{gap} log line(s) lack trace_id. They cannot be cited "
                    f"as evidence and will not contribute to confidence boosts.",
                    affected_count=gap,
                )
            )

    # ── Score: average of applicable coverages ──────────────────────
    applicable = [c for c in coverages if c.is_applicable]
    score = sum(c.ratio for c in applicable) / len(applicable) if applicable else 0.0

    if score >= HIGH_CONFIDENCE_FLOOR:
        band = "high"
    elif score >= LOW_CONFIDENCE_CEILING:
        band = "medium"
    else:
        band = "low"

    # ── Which rules can/cannot fire on this telemetry ───────────────
    likely, will_not = _rules_assessment(ct)

    return QualityAssessment(
        score=round(score, 2),
        confidence_band=band,
        coverages=coverages,
        findings=findings,
        rules_likely_to_fire=likely,
        rules_will_not_fire=will_not,
    )


def _likely_entry_spans(spans) -> list:
    """Entry-point spans: those without a parent in the slice, or
    whose parent is not in the slice (root-of-trace heuristic)."""
    span_ids = {s.span_id for s in spans}
    return [s for s in spans if not s.parent_span_id or s.parent_span_id not in span_ids]


def _rules_assessment(ct) -> tuple[list[str], list[str]]:
    """For each shipped rule, declare whether the telemetry SHOULD let
    it fire based on contract presence — independent of whether the
    failure pattern actually triggers it."""
    from .contracts import RULE_CONTRACTS

    signals = ct.signals
    likely: list[str] = []
    will_not: list[str] = []

    has_business_keys = signals.business_keys_enabled()
    has_state_transitions = any(signals.state_transitions(s) for s in ct.spans)
    has_retry_attempts = any(signals.retry_attempt(s) is not None for s in ct.spans)
    has_pool_stats = signals.pool_signals_enabled() and any(
        signals.pool_stats(s) is not None for s in ct.spans
    )
    has_handler_spans = any(signals.is_handler_span(s) for s in ct.spans)
    has_cross_service_errors = _any_cross_service_error_pair(ct)

    rule_status = {
        "concurrent_modification": has_business_keys and has_state_transitions,
        "retry_storm": has_retry_attempts,
        "downstream_error": has_cross_service_errors,
        "db_pool_exhaustion": has_pool_stats,
        "latency_vs_db": has_handler_spans,
    }
    for c in RULE_CONTRACTS:
        if rule_status.get(c.rule_id, False):
            likely.append(c.rule_id)
        else:
            will_not.append(c.rule_id)
    return likely, will_not


def _any_cross_service_error_pair(ct) -> bool:
    by_id = {s.span_id: s for s in ct.spans}
    for s in ct.spans:
        if not s.is_error or not s.parent_span_id:
            continue
        parent = by_id.get(s.parent_span_id)
        if parent and parent.is_error and parent.service_name != s.service_name:
            return True
    return False
