"""Detect an error chain crossing a service boundary.

Walks the span tree looking for an ERROR span whose nearest descendant
in a different service is also ERROR. The lowest such error is the
originating service. No knowledge of failure injection.
"""

from __future__ import annotations

from ...correlator.models import CorrelatedTelemetry, Span
from ..models import Evidence, Hypothesis
from .base import jaeger_link


def _describe_downstream_status(span: Span, signals) -> str:
    """Best-effort human description of why a downstream span errored.

    Order of preference:
      1. explicit ``status_message`` on the span
      2. canonical HTTP status (via Signals, config-driven)
      3. fallback "ERROR"
    """
    if span.status_message:
        return span.status_message
    code = signals.http_status(span)
    if code is not None:
        return f"HTTP {code}"
    return "ERROR"


class DownstreamErrorRule:
    rule_id = "downstream_error"

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]:
        signals = ct.signals
        children: dict[str, list] = {}
        for s in ct.spans:
            if s.parent_span_id:
                children.setdefault(s.parent_span_id, []).append(s)

        chains: list[tuple] = []
        for s in ct.spans:
            if not s.is_error:
                continue
            for d in children.get(s.span_id, []):
                if d.is_error and d.service_name != s.service_name:
                    chains.append((s, d))

        if not chains:
            return []

        evidence: list[Evidence] = []
        downstream_services: set[str] = set()
        for upstream, downstream in chains:
            downstream_services.add(downstream.service_name)
            evidence.append(
                Evidence(
                    kind="span",
                    description=(
                        f"{upstream.service_name}.{upstream.operation_name} ERROR "
                        f"caused by {downstream.service_name}.{downstream.operation_name} ERROR"
                        + (f": {downstream.status_message}" if downstream.status_message else "")
                    ),
                    trace_id=upstream.trace_id,
                    span_id=upstream.span_id,
                    service=upstream.service_name,
                    link=jaeger_link(upstream.trace_id),
                )
            )

        # Corroborating ERROR logs. Match by either:
        #   - exact service_name in the downstream set, OR
        #   - common normalisation (strip `-service` suffix), OR
        #   - same trace_id (most reliable — logs joined by trace already
        #     belong to the failing request).
        # The previous code only did the suffix-stripped match, which
        # silently dropped logs from services whose names don't follow
        # the demo's "foo-service" convention. Field test
        # (arip-fieldtest/03-downstream-error) was blocked by this.
        trace_ids_in_chain = {up.trace_id for up, _ in chains}
        norm_downstream = downstream_services | {
            s.removesuffix("-service") for s in downstream_services
        }
        for log in ct.logs:
            if log.level != "ERROR":
                continue
            log_relevant = (
                log.service_name in norm_downstream
                or (log.trace_id and log.trace_id in trace_ids_in_chain)
            )
            if not log_relevant:
                continue
            evidence.append(
                Evidence(
                    kind="log",
                    description=f"{log.service_name}: {log.message}",
                    trace_id=log.trace_id,
                    service=log.service_name,
                    snippet=str(log.fields),
                )
            )

        downstream = next(iter(downstream_services))
        downstream_msg = _describe_downstream_status(chains[0][1], signals)

        # Validate the "every span above is ERROR" claim before emitting it.
        # In partial-failure cases (e.g. an attempt that errored within a
        # retry loop where a later attempt recovered) the outer spans are
        # OK, not ERROR. Don't overclaim.
        downstream_span = chains[0][1]
        fully_propagated = _full_ancestor_chain_is_error(downstream_span, ct.spans)

        if fully_propagated:
            propagation_phrase = (
                f"Every span above it in the call stack is ERROR-tagged, "
                f"which means {downstream} is the originating service. No "
                f"span tree above {downstream} contributed a fault — the "
                f"upstream services are just propagating the error."
            )
            confidence = 0.9
        else:
            propagation_phrase = (
                f"The error appears in the immediate parent of the "
                f"{downstream} span, but ancestors further up the call "
                f"stack are NOT ERROR-tagged — the upstream eventually "
                f"recovered (e.g. via retry) or the error was localised. "
                f"This {downstream} fault is a real signal but is not "
                f"necessarily what caused the request to fail end-to-end."
            )
            # Lower confidence — the downstream error existed but the
            # failure surfacing was not solely caused by it.
            confidence = 0.75

        return [
            Hypothesis(
                rule_id=self.rule_id,
                title=f"Downstream {downstream} failure propagated upstream"
                if fully_propagated
                else f"Downstream {downstream} failure observed (recovered upstream)",
                description=(
                    f"The failing request bottomed out in {downstream} with: "
                    f"`{downstream_msg}`. {propagation_phrase}"
                ),
                confidence=confidence,
                severity="high",
                evidence=evidence,
                suggested_next_step=(
                    f"Inspect the {downstream} span in Jaeger and the {downstream} logs "
                    "around the failure timestamp to identify the root error."
                ),
            )
        ]


def _full_ancestor_chain_is_error(downstream_span, all_spans) -> bool:
    """Return True iff EVERY ancestor of ``downstream_span`` up to the root
    is itself ERROR-tagged. This is what makes the "every span above" claim
    technically true vs misleading.
    """
    span_by_id = {s.span_id: s for s in all_spans}
    current = downstream_span
    while current.parent_span_id:
        parent = span_by_id.get(current.parent_span_id)
        if parent is None:
            # Broken chain — we cannot prove "every", so deny.
            return False
        if not parent.is_error:
            return False
        current = parent
    return True
