"""Detect concurrent modification of the same business entity.

This rule has no knowledge of the demo's "webhook race" scenario by
name. It works from natural telemetry only:

  1. Spans tagged with the same ``order.id`` (a normal cross-service
     business correlation tag).
  2. Whether those spans overlap in wall-clock time.
  3. Whether each in-flight side actually mutated the order (visible
     as ``state.transition`` span events).
  4. Whether the application itself emitted a WARN log about finding
     the order in an unexpected state (corroborating signal).

If two traces overlap in time AND each performs a state transition on
the same order, that is a concurrent modification pattern — a class
of failure of which "webhook arrived mid-checkout" is one example.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from ...correlator.models import CorrelatedTelemetry, LogEntry, Span
from ..models import Evidence, Hypothesis
from .base import jaeger_link


class WebhookRaceRule:
    rule_id = "concurrent_modification"

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]:
        signals = ct.signals
        # Cross-trace correlation needs a business key. If the
        # environment did not configure any, gracefully no-op.
        if not signals.business_keys_enabled():
            return []
        # 1) Group every span carrying a business key by that key.
        by_order: dict[str, list[Span]] = defaultdict(list)
        for s in ct.spans:
            key = signals.business_key_for(s)
            if key:
                by_order[key].append(s)

        hypotheses: list[Hypothesis] = []
        for order_id, spans in by_order.items():
            traces = _group_by_trace(spans)
            if len(traces) < 2:
                continue

            # 2) Find any pair of traces whose lifetimes overlap.
            overlaps = _overlapping_trace_pairs(traces)
            if not overlaps:
                continue

            for trace_a, trace_b, overlap in overlaps:
                a_transitions = _state_transitions(traces[trace_a], signals)
                b_transitions = _state_transitions(traces[trace_b], signals)
                # 3) Only confirm a race if BOTH sides actually mutated state.
                if not a_transitions or not b_transitions:
                    continue
                # The "inner" trace is the one fully contained in the
                # other — usually the short, late-arriving operation.
                inner_trace, outer_trace = _pick_inner_outer(
                    trace_a, trace_b, traces[trace_a], traces[trace_b]
                )
                inner_transitions = a_transitions if inner_trace == trace_a else b_transitions
                outer_transitions = b_transitions if inner_trace == trace_a else a_transitions
                evidence = _build_evidence(
                    order_id=order_id,
                    inner_trace=inner_trace,
                    outer_trace=outer_trace,
                    inner_spans=traces[inner_trace],
                    outer_spans=traces[outer_trace],
                    inner_transitions=inner_transitions,
                    outer_transitions=outer_transitions,
                    overlap_ms=overlap,
                    logs=ct.logs,
                )
                inner_op = _root_op(traces[inner_trace])
                outer_op = _root_op(traces[outer_trace])
                hypotheses.append(
                    Hypothesis(
                        rule_id=self.rule_id,
                        title=(f"Concurrent modification across `{outer_op}` and `{inner_op}`"),
                        description=(
                            f"Two separate traces mutated order `{order_id}` while "
                            f"overlapping in time by ~{overlap:.0f}ms. The longer "
                            f"operation `{outer_op}` was already in flight when "
                            f"`{inner_op}` ran end-to-end and changed the order's "
                            f"state. Neither side observed the other's transition "
                            f"before acting. This is a classic concurrent-modification "
                            f"pattern; the most common real-world instance is an "
                            f"asynchronous callback (webhook, event consumer) "
                            f"completing before the synchronous flow that initiated "
                            f"the underlying work."
                        ),
                        confidence=_confidence_score(evidence),
                        severity="high",
                        evidence=evidence,
                        suggested_next_step=(
                            f"Establish a single authority for `{order_id}`'s state "
                            f"transitions (e.g. require `{inner_op}` to wait for "
                            f"`{outer_op}` to complete, or gate the transition on "
                            f"the expected previous state)."
                        ),
                    )
                )
        return hypotheses


# --- internals -------------------------------------------------------


def _group_by_trace(spans: Iterable[Span]) -> dict[str, list[Span]]:
    by_trace: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        by_trace[s.trace_id].append(s)
    return by_trace


def _overlapping_trace_pairs(
    traces: dict[str, list[Span]],
) -> list[tuple[str, str, float]]:
    """Return (trace_a, trace_b, overlap_ms) for every overlapping pair."""
    windows = {
        t: (min(s.start_time for s in spans), max(s.end_time for s in spans))
        for t, spans in traces.items()
    }
    out: list[tuple[str, str, float]] = []
    items = list(windows.items())
    for i in range(len(items)):
        a_id, (a_start, a_end) = items[i]
        for j in range(i + 1, len(items)):
            b_id, (b_start, b_end) = items[j]
            overlap_start = max(a_start, b_start)
            overlap_end = min(a_end, b_end)
            if overlap_end > overlap_start:
                ms = (overlap_end - overlap_start).total_seconds() * 1000
                out.append((a_id, b_id, ms))
    return out


def _state_transitions(spans: Iterable[Span], signals) -> list[dict]:
    """Return canonical state-transition events as plain dicts. Uses
    Signals so the event name + attribute names are config-driven."""
    out: list[dict] = []
    for s in spans:
        for st in signals.state_transitions(s):
            out.append(
                {
                    "timestamp": st.timestamp,
                    "from": st.from_state,
                    "to": st.to_state,
                    "order_id": st.entity_id,
                    "trace_id": st.trace_id,
                    "span_id": st.span_id,
                    "service": st.service,
                }
            )
    return out


def _service_for_op(spans: list[Span], op: str) -> str:
    for s in spans:
        if s.operation_name == op:
            return s.service_name
    return spans[0].service_name


def _root_op(spans: list[Span]) -> str:
    """Best-effort name for a trace: its earliest non-server-wrapper span."""
    # Prefer a span whose operation name looks like an application
    # method (contains a dot or an underscore), falling back to the
    # earliest by start time.
    candidates = [s for s in spans if "." in s.operation_name or "_" in s.operation_name]
    pool = candidates or spans
    pool = sorted(pool, key=lambda s: s.start_time)
    return pool[0].operation_name if pool else "?"


def _pick_inner_outer(
    a_id: str, b_id: str, a_spans: list[Span], b_spans: list[Span]
) -> tuple[str, str]:
    """Return (inner_trace_id, outer_trace_id) where ``inner`` is the
    shorter-lived trace (the one that "arrived while the other was in
    flight"). Ties resolved deterministically by trace_id."""
    a_dur = _duration(a_spans)
    b_dur = _duration(b_spans)
    if a_dur < b_dur:
        return a_id, b_id
    if b_dur < a_dur:
        return b_id, a_id
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def _duration(spans: list[Span]) -> float:
    start = min(s.start_time for s in spans)
    end = max(s.end_time for s in spans)
    return (end - start).total_seconds()


def _build_evidence(
    *,
    order_id: str,
    inner_trace: str,
    outer_trace: str,
    inner_spans: list[Span],
    outer_spans: list[Span],
    inner_transitions: list[dict],
    outer_transitions: list[dict],
    overlap_ms: float,
    logs: list[LogEntry],
) -> list[Evidence]:
    evidence: list[Evidence] = []

    inner_op = _root_op(inner_spans)
    outer_op = _root_op(outer_spans)
    inner_start = min(s.start_time for s in inner_spans)
    inner_end = max(s.end_time for s in inner_spans)
    outer_start = min(s.start_time for s in outer_spans)
    outer_end = max(s.end_time for s in outer_spans)

    evidence.append(
        Evidence(
            kind="span",
            description=(
                f"`{outer_op}` ran {outer_start.isoformat()} → "
                f"{outer_end.isoformat()} on order `{order_id}`"
            ),
            trace_id=outer_trace,
            service=_service_for_op(outer_spans, outer_op),
            link=jaeger_link(outer_trace),
        )
    )
    evidence.append(
        Evidence(
            kind="span",
            description=(
                f"`{inner_op}` ran {inner_start.isoformat()} → "
                f"{inner_end.isoformat()} (fully inside `{outer_op}`'s window; "
                f"~{overlap_ms:.0f}ms overlap) on order `{order_id}`"
            ),
            trace_id=inner_trace,
            service=_service_for_op(inner_spans, inner_op),
            link=jaeger_link(inner_trace),
        )
    )

    for tr in inner_transitions + outer_transitions:
        ts = tr.get("timestamp")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else "?"
        evidence.append(
            Evidence(
                kind="span_event",
                description=(
                    f"state.transition {tr.get('from')} → {tr.get('to')} "
                    f"on order `{order_id}` at {ts_str}"
                ),
                trace_id=tr.get("trace_id"),
                span_id=tr.get("span_id"),
                service=tr.get("service"),
            )
        )

    for log in logs:
        if log.level == "WARN" and order_id in str(log.fields.get("order_id", "")):
            evidence.append(
                Evidence(
                    kind="log",
                    description=f"{log.service_name}: {log.message}",
                    trace_id=log.trace_id,
                    service=log.service_name,
                    snippet=str(log.fields),
                )
            )

    return evidence


def _confidence_score(evidence: list[Evidence]) -> float:
    """Confidence rises with the strength of corroborating evidence."""
    has_transition = any(e.kind == "span_event" for e in evidence)
    has_warn_log = any(e.kind == "log" for e in evidence)
    if has_transition and has_warn_log:
        return 0.92
    if has_transition:
        return 0.8
    return 0.6
