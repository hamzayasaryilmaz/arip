"""Detect database connection pool exhaustion.

Distinguishes pool exhaustion from neighbouring patterns:

  * slow_query        — handler-level sleep before any DB call;
                        ``db.*`` spans are all fast.
  * downstream_timeout — payment-side timeout waiting on inventory;
                        no DB span on the originating service.
  * pool_exhaustion   — latency lives in a ``db.acquire_connection``
                        span; pool stats show saturation; the actual
                        ``db.decrement_stock`` query is normal.

The rule is **strictly evidence-gated**: it requires the
``db.pool.*`` attribute family on at least one span. Without those
attributes, the rule abstains (returns no hypothesis). A symptom
that *looks* like pool exhaustion but lacks the pool stats is by
construction not investigable by this rule — and the engine-level
abstention pathway will then surface "no rule matched" honestly.
"""

from __future__ import annotations

from ...correlator.models import CorrelatedTelemetry, Span
from ..models import Evidence, Hypothesis
from .base import jaeger_link

# A span counts as "showing pool saturation" if either:
#  - the pool was at capacity at the moment the span ran, or
#  - the caller waited measurably for a connection.
SATURATION_WAIT_MS = 100


class PoolExhaustionRule:
    rule_id = "db_pool_exhaustion"

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]:
        signals = ct.signals
        # If the environment did not configure pool signals, this rule
        # cannot make any honest claim — abstain gracefully.
        if not signals.pool_signals_enabled():
            return []

        saturated: list[tuple[Span, int, int, int, int]] = []
        for s in ct.spans:
            stats = signals.pool_stats(s)
            if stats is None:
                continue
            if stats.acquired is None or stats.max_size is None or stats.wait_ms is None:
                continue
            slow_acquire = stats.wait_ms >= SATURATION_WAIT_MS
            if not (stats.at_capacity or slow_acquire):
                continue
            saturated.append(
                (s, stats.acquired, stats.max_size, stats.wait_ms, stats.empty_acquires_total or 0)
            )

        if not saturated:
            return []

        # Pick the worst single piece of evidence — the longest acquire
        # wait. Tie-break by trace_id for determinism.
        saturated.sort(key=lambda x: (x[3], x[0].trace_id), reverse=True)
        worst_span, acquired, max_conns, wait_ms, empties = saturated[0]
        service = worst_span.service_name

        evidence: list[Evidence] = []
        evidence.append(
            Evidence(
                kind="span",
                description=(
                    f"`{worst_span.operation_name}` waited {wait_ms}ms for "
                    f"a connection; pool at {acquired}/{max_conns} in-use "
                    f"({empties} empty-acquires recorded since process "
                    f"start)."
                ),
                trace_id=worst_span.trace_id,
                span_id=worst_span.span_id,
                service=service,
                link=jaeger_link(worst_span.trace_id),
                snippet=str(
                    {
                        "db.pool.acquired": acquired,
                        "db.pool.max": max_conns,
                        "db.pool.wait_ms": wait_ms,
                        "db.pool.empty_acquires_total": empties,
                    }
                ),
            )
        )

        # Contrast: what does the actual SQL look like? If it's fast,
        # that proves the DB itself is healthy and the pool is the
        # bottleneck.
        for s in ct.spans:
            if (
                s.trace_id == worst_span.trace_id
                and signals.is_db_span(s)
                and not signals.is_db_acquire_span(s)
                and signals.pool_stats(s) is None
            ):
                evidence.append(
                    Evidence(
                        kind="span",
                        description=(
                            f"`{s.operation_name}` itself only took "
                            f"{s.duration_us / 1000:.1f}ms — the database "
                            f"layer is healthy, the wait is at the pool."
                        ),
                        trace_id=s.trace_id,
                        span_id=s.span_id,
                        service=s.service_name,
                    )
                )
                break

        # Upstream timeout / error evidence — what the test actually saw.
        for s in ct.spans:
            if s.trace_id == worst_span.trace_id and s.is_error:
                msg = s.status_message or "ERROR"
                evidence.append(
                    Evidence(
                        kind="span",
                        description=(
                            f"Upstream `{s.service_name}.{s.operation_name}` surfaced ERROR: {msg}"
                        ),
                        trace_id=s.trace_id,
                        span_id=s.span_id,
                        service=s.service_name,
                    )
                )

        # Corroborating logs — pool-related WARN/ERROR.
        for log in ct.logs:
            if log.level in {"WARN", "ERROR"} and (
                "pool" in log.message.lower() or "acquire" in log.message.lower()
            ):
                evidence.append(
                    Evidence(
                        kind="log",
                        description=f"{log.service_name}: {log.message}",
                        trace_id=log.trace_id,
                        service=log.service_name,
                        snippet=str(log.fields),
                    )
                )

        return [
            Hypothesis(
                rule_id=self.rule_id,
                title=f"Database connection pool exhaustion in {service}",
                description=(
                    f"`{service}` exhausted its database connection pool. "
                    f"A `{worst_span.operation_name}` span waited "
                    f"{wait_ms}ms with the pool at {acquired}/{max_conns} "
                    f"connections in use. The latency is **not** in the "
                    f"query — the query span itself is fast — it is in "
                    f"waiting for a free connection. This is the "
                    f"distinguishing signature of pool exhaustion vs. a "
                    f"slow query: pool-related signals on the acquire "
                    f"span, while the actual SQL stays normal."
                ),
                confidence=_confidence_score(evidence, empties=empties),
                severity="high",
                evidence=evidence,
                suggested_next_step=(
                    f"Either raise `MaxConns` for {service}, or shorten "
                    f"per-request connection-hold time. Look for long "
                    f"transactions, missing batching, or slow operations "
                    f"that check a connection out for the duration of a "
                    f"request rather than just the query."
                ),
            )
        ]


def _as_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _confidence_score(evidence: list[Evidence], *, empties: int) -> float:
    """Confidence rises with corroborating signal strength:

    - baseline 0.80 (pool stats + saturated acquire span)
    - +0.05 if there's a healthy-query contrast span
    - +0.05 if there's a WARN/ERROR log mentioning the pool
    - +0.03 if empty_acquires > 0 (proves the pool actually ran dry)
    """
    score = 0.80
    if any(e.kind == "span" and "healthy" in e.description for e in evidence):
        score += 0.05
    if any(e.kind == "log" for e in evidence):
        score += 0.05
    if empties > 0:
        score += 0.03
    return min(score, 0.95)
