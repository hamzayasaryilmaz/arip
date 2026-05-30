"""Differentiate application latency from database latency.

A common debugging dead-end is "the call is slow — must be the DB". This
rule looks at the handler span vs the DB span beneath it: if the handler
took materially longer than the DB, the latency is *not* in the DB.
"""

from __future__ import annotations

from ...correlator.models import CorrelatedTelemetry
from ..models import Evidence, Hypothesis
from .base import jaeger_link

# A handler that takes >200ms AND >10x its DB span duration is anomalous.
# Field test (arip-fieldtest/) showed the previous 50ms floor matched
# nearly every healthy auto-instrumented handler — they're typically
# 80-200ms with sub-10ms DB work, which trivially crosses 10×.
# MIN_DB_US filters out DB spans so fast the ratio is meaningless
# (e.g. 100ms handler / 0.05ms cached read = 2000× — pure noise);
# 500us (0.5ms) is small enough to let real Postgres INSERTs through
# (typically 1-3ms each on local hardware).
MIN_HANDLER_US = 200_000
MIN_DB_US = 500
RATIO_THRESHOLD = 10.0


class LatencyVsDBRule:
    rule_id = "latency_vs_db"

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]:
        signals = ct.signals
        by_parent: dict[str, list] = {}
        for s in ct.spans:
            if s.parent_span_id:
                by_parent.setdefault(s.parent_span_id, []).append(s)

        hypotheses: list[Hypothesis] = []
        for handler in ct.spans:
            if not signals.is_handler_span(handler):
                continue
            if handler.duration_us < MIN_HANDLER_US:
                continue
            db_children = [c for c in by_parent.get(handler.span_id, []) if signals.is_db_span(c)]
            if not db_children:
                continue
            db_total = sum(c.duration_us for c in db_children)
            if db_total < MIN_DB_US:
                continue
            ratio = handler.duration_us / db_total
            if ratio < RATIO_THRESHOLD:
                continue

            evidence = [
                Evidence(
                    kind="span",
                    description=(
                        f"{handler.service_name}.{handler.operation_name} ran for "
                        f"{handler.duration_us / 1000:.1f}ms but its DB work was only "
                        f"{db_total / 1000:.1f}ms (~{ratio:.0f}× ratio). The latency is "
                        "above the DB layer."
                    ),
                    trace_id=handler.trace_id,
                    span_id=handler.span_id,
                    service=handler.service_name,
                    link=jaeger_link(handler.trace_id),
                ),
            ]
            for c in db_children:
                evidence.append(
                    Evidence(
                        kind="span",
                        description=(
                            f"DB span `{c.operation_name}` took {c.duration_us / 1000:.1f}ms"
                        ),
                        trace_id=c.trace_id,
                        span_id=c.span_id,
                        service=c.service_name,
                    )
                )

            hypotheses.append(
                Hypothesis(
                    rule_id=self.rule_id,
                    title=f"Latency above the database layer in {handler.service_name}",
                    description=(
                        f"`{handler.operation_name}` is slow, but the DB work it "
                        f"performs is fast ({handler.duration_us / 1000:.0f}ms handler "
                        f"vs {db_total / 1000:.0f}ms DB). The bottleneck is not in "
                        f"PostgreSQL — it is in the handler itself, before or after "
                        f"the DB call. Look for synchronous I/O, sleeps, blocking "
                        f"locks, or external calls."
                    ),
                    confidence=0.85,
                    severity="medium",
                    evidence=evidence,
                    # Field test F6: a 10× handler-over-DB ratio above
                    # the absolute floors IS the evidence. Healthy code
                    # paths don't co-emit error logs for "handler is
                    # slow" — there's nothing for the log layer to add.
                    # The sharp thresholds (200ms handler, 5ms DB min,
                    # 10× ratio) already enforce a strong signal.
                    min_evidence_kinds=1,
                    suggested_next_step=(
                        "Profile the handler before and after the DB call. Look for "
                        "synchronous I/O, sleeps, lock contention, or external calls."
                    ),
                )
            )
        return hypotheses
