"""Telemetry prerequisite gate.

Runs BEFORE the engine touches anything. Asks the single hard
question: is this telemetry distributed-tracing-shaped?

ARIP's entire trust model rests on `trace_id` linking events across
services. If that propagation isn't there, the engine should refuse
to run rather than produce plausible-looking nonsense from one-shot
log lines.

Three checks, all hard:
  1. Spans exist at all.
  2. ≥ 1 span carries a non-empty trace_id.
  3. Either (a) ≥ 2 services participate in the trace,
     OR (b) parent_span_id chains exist within a single service
     (single-service hop is OK if it forms a real tree).

If any check fails → `PrerequisiteFailure` with a specific reason
and an actionable hint. The CLI translates this into a fail-fast
exit with operator guidance instead of running the engine.

This is deliberately STRICT. ARIP would rather say "your telemetry
isn't ready for me" than try to investigate without distributed
context.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..correlator.models import CorrelatedTelemetry


@dataclass(frozen=True)
class PrerequisiteFailure:
    """Specific reason ARIP can't reason about this telemetry yet."""

    code: str  # 'no_spans' | 'no_trace_id' | 'no_propagation'
    headline: str
    detail: str
    next_step: str  # Concrete telemetry-hygiene action for the operator


def check_prerequisites(ct: CorrelatedTelemetry) -> PrerequisiteFailure | None:
    """Return a failure reason if ARIP cannot meaningfully run, else None.

    Engine path callers should treat a non-None result as fail-fast:
    do NOT run rules, do NOT produce hypotheses, surface this to the
    operator with the embedded next_step.
    """
    if not ct.spans:
        return PrerequisiteFailure(
            code="no_spans",
            headline="No spans available in the telemetry bundle.",
            detail=(
                "ARIP requires OpenTelemetry-shaped spans to reason about "
                "distributed requests. The bundle ARIP was asked to "
                "investigate contains zero spans."
            ),
            next_step=(
                "Verify your telemetry export contains span data (Jaeger "
                "trace JSON, Tempo OTLP output, etc.). If your services "
                "emit only logs and no tracing, you need to add OpenTelemetry "
                "tracing instrumentation before ARIP can help. See "
                "docs/ONBOARDING.md 'Minimum viable signals'."
            ),
        )

    has_trace_id = any(s.trace_id for s in ct.spans)
    if not has_trace_id:
        return PrerequisiteFailure(
            code="no_trace_id",
            headline="No span carries a trace_id.",
            detail=(
                f"ARIP found {len(ct.spans)} span(s) but none of them have "
                "a trace_id. ARIP cannot correlate events across services "
                "without a trace identifier."
            ),
            next_step=(
                "Check your OpenTelemetry instrumentation — every span should "
                "carry the trace_id. If you're using a non-OTel tracer (Zipkin "
                "B3, custom), ensure the adapter mapping in your "
                "NormalizationConfig points the trace_id field correctly. "
                "See docs/ONBOARDING.md 'Writing your config'."
            ),
        )

    # Distributed-context check: either cross-service or in-service propagation.
    services = {s.service_name for s in ct.spans if s.service_name}
    has_propagation = _has_parent_chain(ct) or len(services) >= 2

    if not has_propagation:
        return PrerequisiteFailure(
            code="no_propagation",
            headline="No distributed-context propagation detected.",
            detail=(
                f"ARIP found {len(ct.spans)} span(s) from {len(services)} "
                "service(s), but no parent_span_id chains exist and only "
                "one service is involved. Without propagation, ARIP cannot "
                "reconstruct what happened across the request."
            ),
            next_step=(
                "If you have multi-service requests, verify your services "
                "propagate the W3C traceparent header (or B3 if Zipkin). "
                "Some likely causes: missing OTel middleware on one service, "
                "client library that doesn't auto-inject headers, or a "
                "service boundary that strips them (an API gateway is the "
                "common culprit). See docs/ONBOARDING.md."
            ),
        )

    return None


def _has_parent_chain(ct: CorrelatedTelemetry) -> bool:
    """At least one span has a parent_span_id that resolves within the bundle."""
    span_ids = {s.span_id for s in ct.spans if s.span_id}
    for s in ct.spans:
        if s.parent_span_id and s.parent_span_id in span_ids:
            return True
    return False
