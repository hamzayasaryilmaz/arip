"""Detect retry storms — request amplification driven by an aggressive
retry policy against a consistently-failing downstream.

Telemetry contract this rule reads against:

  * Spans carry ``retry.attempt`` (1..N) when produced inside a retry
    loop.
  * The same logical operation name repeats across attempts in the
    same trace (e.g. ``inventory.reserve_attempt``).
  * Backoff is recorded as ``retry.backoff_ms`` per attempt.
  * The reason for retrying is captured as ``retry.reason``.
  * The policy is identified by ``retry.policy``
    (``exponential``/``linear``/``fixed``).

What this rule deliberately does NOT do:

  * Speculate about retry storms when only ONE attempt is visible.
  * Fire when the trace shows transient failures without retries
    (that's a downstream_error, not a storm).
  * Cite spans whose retry metadata is missing or malformed —
    everything cited must be a real, attribute-grounded reference.
"""

from __future__ import annotations

from collections import defaultdict

from ...correlator.models import CorrelatedTelemetry, Span
from ..models import Evidence, Hypothesis
from .base import jaeger_link

MIN_ATTEMPTS_FOR_STORM = 2


class RetryStormRule:
    rule_id = "retry_storm"

    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]:
        signals = ct.signals
        attempt_spans = [s for s in ct.spans if signals.retry_attempt(s) is not None]
        if not attempt_spans:
            return []

        # Group attempts that share both trace AND operation — these are
        # retries of the same logical step within one request.
        chains: dict[tuple[str, str], list[Span]] = defaultdict(list)
        for s in attempt_spans:
            chains[(s.trace_id, s.operation_name)].append(s)

        # Reduce to chains long enough to call a "storm".
        storms = {k: v for k, v in chains.items() if len(v) >= MIN_ATTEMPTS_FOR_STORM}
        if not storms:
            return []

        # Pick the worst chain (most attempts; tie-break by trace_id).
        worst_key = max(storms.keys(), key=lambda k: (len(storms[k]), k[1], k[0]))
        chain = sorted(
            storms[worst_key],
            key=lambda s: (signals.retry_attempt(s) or 0, s.start_time),
        )
        trace_id, operation = worst_key
        upstream_service = chain[0].service_name

        backoffs = [signals.retry_backoff_ms(s) or 0 for s in chain]
        reasons = [signals.retry_reason(s) for s in chain if signals.retry_reason(s)]
        max_attempts_field = signals.retry_max_attempts(chain[-1])
        policy = signals.retry_policy(chain[-1]) or "?"

        errored = sum(1 for s in chain if s.is_error)
        attempts_used = len(chain)

        # Validate the strong "every attempt failed with the same reason"
        # claim before emitting it. In partial-failure cases (e.g. an
        # eventually-successful retry) only the failing attempts have a
        # retry.reason — counting only those would falsely report
        # "consistent". Anchor against the full attempt set.
        all_attempts_errored = errored == attempts_used
        unique_reasons = {r.strip() if isinstance(r, str) else r for r in reasons}
        truly_persistent = all_attempts_errored and len(unique_reasons) == 1 and bool(reasons)

        # Temporal: cumulative wall-clock time spent in the chain
        # (start of first attempt → end of last attempt).
        chain_start = min(s.start_time for s in chain)
        chain_end = max(s.end_time for s in chain)
        cumulative_ms = (chain_end - chain_start).total_seconds() * 1000

        is_exponential = _looks_exponential(backoffs)
        # `truly_persistent` (computed above) is what gates both
        # the strong "every attempt failed with the same reason"
        # description AND the consistent-reason confidence bump.
        # We use the same stricter test in both places intentionally.
        exhausted = max_attempts_field is not None and attempts_used >= max_attempts_field

        # --- evidence assembly --------------------------------------

        evidence: list[Evidence] = []

        for s in chain:
            # Build the snippet from the canonical signal getters so the
            # evidence is portable across telemetry conventions.
            ev_attrs = {
                "retry.attempt": signals.retry_attempt(s),
                "retry.max_attempts": signals.retry_max_attempts(s),
                "retry.backoff_ms": signals.retry_backoff_ms(s),
                "retry.policy": signals.retry_policy(s),
                "retry.reason": signals.retry_reason(s),
            }
            evidence.append(
                Evidence(
                    kind="span",
                    description=(
                        f"`{s.operation_name}` attempt "
                        f"{signals.retry_attempt(s) if signals.retry_attempt(s) is not None else '?'}/"
                        f"{signals.retry_max_attempts(s) if signals.retry_max_attempts(s) is not None else '?'} "
                        f"after {signals.retry_backoff_ms(s) if signals.retry_backoff_ms(s) is not None else '?'}ms backoff "
                        f"— {'ERROR' if s.is_error else 'OK'}"
                    ),
                    trace_id=s.trace_id,
                    span_id=s.span_id,
                    service=s.service_name,
                    link=jaeger_link(s.trace_id),
                    snippet=str(ev_attrs),
                )
            )

        # Add the downstream service's error/log signals that triggered
        # the retries. Phrase precisely — "each" only if EVERY attempt
        # hit a downstream error; otherwise "some" with the count.
        downstream_errors = [
            s
            for s in ct.spans
            if s.trace_id == trace_id and s.is_error and s.service_name != upstream_service
        ]
        if downstream_errors:
            d = downstream_errors[0]
            n_errored_downstream = len(downstream_errors)
            if all_attempts_errored and n_errored_downstream >= attempts_used:
                downstream_description = (
                    f"Each of the {attempts_used} attempts hit "
                    f"`{d.service_name}.{d.operation_name}` ERROR: "
                    f"{d.status_message or 'no message'}. The downstream "
                    f"was consistently failing — retries are the symptom, the "
                    f"downstream is the root cause."
                )
            else:
                downstream_description = (
                    f"{n_errored_downstream} of the {attempts_used} attempts "
                    f"hit `{d.service_name}.{d.operation_name}` ERROR "
                    f"(status: {d.status_message or 'no message'}). The "
                    f"retry policy recovered the request — this is a "
                    f"transient downstream blip, not a persistent failure."
                )
            evidence.append(
                Evidence(
                    kind="span",
                    description=downstream_description,
                    trace_id=d.trace_id,
                    span_id=d.span_id,
                    service=d.service_name,
                )
            )

        # Corroborating logs in the same trace. We include WARN as well
        # as ERROR — for retry scenarios specifically, the per-attempt
        # transient failures are typically logged at WARN (because they
        # recovered), and excluding them meant the rule shipped only
        # span-kind evidence and got blocked by MIN_EVIDENCE_KINDS=2.
        # Field test (arip-fieldtest/01-retry-storm) was 100% blocked
        # by this.
        for log in ct.logs:
            if log.trace_id != trace_id:
                continue
            if log.level not in ("ERROR", "WARN", "WARNING"):
                continue
            evidence.append(
                Evidence(
                    kind="log",
                    description=f"[{log.level}] {log.service_name}: {log.message}",
                    trace_id=log.trace_id,
                    service=log.service_name,
                    snippet=str(log.fields),
                )
            )

        # --- description + ranking -----------------------------------

        amplification = attempts_used  # one logical request → N inventory calls
        backoff_phrase = (
            f" with exponential backoff ({_format_backoffs(backoffs)})" if is_exponential else ""
        )
        exhaustion_phrase = (
            f" The retry policy exhausted at {attempts_used}/{max_attempts_field}; "
            "the client request failed because retries did not recover."
            if exhausted
            else ""
        )
        # Only make the strong "persistent" claim when EVERY attempt
        # actually failed. If the retry succeeded eventually, this was
        # a transient downstream blip — say so.
        if truly_persistent:
            reason_phrase = (
                f" Every attempt failed with the same reason "
                f"(`{reasons[0].strip() if isinstance(reasons[0], str) else reasons[0]}`), "
                "indicating a persistent downstream condition rather than a transient blip."
            )
        elif reasons and errored < attempts_used:
            reason_phrase = (
                f" Only {errored} of {attempts_used} attempts errored "
                f"(reason: `{reasons[0].strip() if isinstance(reasons[0], str) else reasons[0]}`); "
                f"the retry policy recovered the request. This is a transient "
                f"downstream condition, not a persistent failure — but the "
                f"retry chain itself is the latency cost."
            )
        else:
            reason_phrase = ""

        description = (
            f"`{upstream_service}` issued {attempts_used} attempts of "
            f"`{operation}` against the same downstream in a single "
            f"trace{backoff_phrase}. Total wall-time spent in the retry "
            f"chain: {cumulative_ms:.0f}ms. The amplification factor for "
            f"this one logical request is {amplification}× — under "
            f"concurrent load, the downstream sees {amplification}N "
            f"calls for N user requests, which can push a marginally "
            f"degraded service over the edge."
            f"{exhaustion_phrase}{reason_phrase}"
        )

        return [
            Hypothesis(
                rule_id=self.rule_id,
                title=(
                    f"Retry storm: {attempts_used} attempts to `{operation}` in {upstream_service}"
                ),
                description=description,
                confidence=_confidence(
                    has_logs=any(e.kind == "log" for e in evidence),
                    # Only count consistency when retries truly stayed
                    # consistent (all attempts errored, same reason).
                    consistent_reason=truly_persistent,
                    is_exponential=is_exponential,
                    exhausted=exhausted,
                ),
                severity="high",
                evidence=evidence,
                suggested_next_step=(
                    (
                        "Stabilise the downstream first: every retry hit "
                        "the same failure, so adding more retries will "
                        "not help. "
                        if truly_persistent
                        else f"The retry policy recovered the request, but the "
                        f"chain itself adds latency. Consider whether "
                        f"{attempts_used} attempts are appropriate for this "
                        f"call site, and look for a way to make the downstream "
                        f"more reliable so retries are not needed. "
                    )
                    + f"Reconsider the retry policy: {attempts_used} attempts "
                    f"with `{policy}` backoff amplifies load by {amplification}× "
                    f"during incidents and can prolong outages."
                ),
            )
        ]


# --- helpers ----------------------------------------------------------


def _as_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _looks_exponential(backoffs: list[int]) -> bool:
    """Return True if the non-zero backoffs roughly double each step."""
    from itertools import pairwise

    nonzero = [b for b in backoffs if b > 0]
    if len(nonzero) < 2:
        return False
    for prev, curr in pairwise(nonzero):
        if prev == 0:
            continue
        ratio = curr / prev
        if not (1.5 <= ratio <= 3.0):
            return False
    return True


def _format_backoffs(backoffs: list[int]) -> str:
    return "→".join(f"{b}ms" for b in backoffs)


def _confidence(
    *,
    has_logs: bool,
    consistent_reason: bool,
    is_exponential: bool,
    exhausted: bool,
) -> float:
    score = 0.80
    if consistent_reason:
        score += 0.05
    if is_exponential:
        score += 0.04
    if exhausted:
        score += 0.03
    if has_logs:
        score += 0.02
    return min(round(score, 2), 0.95)
