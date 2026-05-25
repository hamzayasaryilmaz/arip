# Calibration gallery

Ten mixed-signal scenarios that codify how ARIP behaves under bad
telemetry. Each is a unit test in
[arip-core/tests/test_calibration_benchmark.py](../arip-core/tests/test_calibration_benchmark.py)
— that file is the regression spec. This page is the readable version,
for engineers evaluating whether ARIP would be trustworthy in their
environment.

The contract every scenario enforces:

> **The engine must never produce a high-confidence wrong RCA on
> degraded telemetry.** It may abstain. It may produce a low-confidence
> hypothesis. It may say "no rule matched". It must NOT confidently
> mislead an engineer.

If a refactor causes any scenario below to violate that contract, the
benchmark test fails and CI rejects it.

## 1 · The trace never arrived

**Input:** `FailureEvent` with a `trace_id` that does not exist in
the telemetry backend (sampled, lost, or simply not yet flushed).

**Expected:** `no_primary_trace` abstention. No hypothesis under any
circumstances.

**Why:** Producing hypotheses from zero spans is the worst failure
mode of an investigation engine — confident output, zero ground
truth. Refusing is the only honest move.

## 2 · A pattern with no matching rule

**Input:** Spans exist, propagation healthy, but no rule's signature
fits — a single fast healthy span representing some niche failure
class the MVP's five rules don't cover.

**Expected:** `no_rule_matched` (or `weak_evidence` if a rule weakly
matches).

**Why:** The MVP's rule library is narrow on purpose. The right
response to a novel pattern is "we don't have coverage", not
"let me guess".

## 3 · Orphan spans from broken propagation

**Input:** An ERROR span whose `parent_span_id` references a span
that isn't in the telemetry slice (e.g. dropped by sampling or a
broken instrumentation path).

**Expected:** No false chain manufactured. The
`propagation_health` coverage in the quality assessment flags the
orphan; the `downstream_error` rule does not invent the missing parent.

**Why:** Span tree walks must be defensive. An orphan must be
visible as an orphan, not silently treated as the trace root.

## 4 · Partial retry metadata

**Input:** Three spans tagged with `retry.attempt = 1/2/3` but no
`retry.reason`, no `retry.backoff_ms`, no `retry.policy`. A trace
where someone instrumented one field but not the whole contract.

**Expected:** `retry_storm` may fire, but confidence < 0.85. The
absent metadata means the rule cannot apply its corroboration
bonuses (exponential detection, exhaustion, consistent reason).

**Why:** Confidence must reflect how much signal the rule actually
verified, not how much it would have liked to verify.

## 5 · HTTP 5xx without OTel ERROR status

**Input:** A span with `http.response.status_code = 500` but
`span.status = OK`. A real-world auto-instrumentation gap.

**Expected:** `downstream_error` rule cannot find an ERROR chain
(because the span's status field is OK). The quality assessment's
`error_status_consistency` coverage drops; a `warn` finding tells
the operator exactly what to fix in their instrumentation.

**Why:** ARIP cannot rewrite history. Misinstrumented telemetry
produces missing findings; the assessment makes that visible to the
operator.

## 6 · Sampled retry chain — only attempts 1 and 5 of 5 visible

**Input:** Mid-chain spans were dropped by sampling. The engine sees
attempts 1 and 5 with their retry metadata.

**Expected:** `retry_storm` fires (≥ 2 attempts present) but does
not claim "every attempt failed with the same reason" — the missing
attempts could have behaved differently. Confidence ≤ 0.95.

**Why:** Sampled telemetry is inherently lossy. Claims about "every"
attempt require seeing every attempt; the rule template hardening
already enforces this.

## 7 · Inconsistent business-key naming

**Input:** Two spans for the same logical order: one uses
`order.id`, another uses `order_id` (typo / mixed instrumentation).
Default config only recognises `order.id`.

**Expected:** No rule fires high-confidence. The quality
assessment's `business_key_on_entry` coverage drops; the operator
sees this as a finding and either fixes the instrumentation or
adds `order_id` to the config's business keys list.

**Why:** Cross-trace correlation is precision-critical. Silently
treating `order.id` and `order_id` as equivalent would be a hidden
heuristic that produces overconfident findings.

## 8 · Quality bands track telemetry richness

**Input:** Two synthetic telemetries — one rich (full demo-style
signal coverage), one thin (single span, no logs, no attrs).

**Expected:** Rich → `high` confidence band. Thin → `low`
confidence band. Surfaced in the report so the engineer knows which
state they are in.

**Why:** The score is the operator's single-glance signal about
whether the engine is working on good or bad input. Bands must
discriminate between the two clearly.

## 9 · Rule readiness reflects telemetry presence

**Input:** Telemetry with retry metadata but no pool stats and no
business keys.

**Expected:** `arip preflight` reports `retry_storm` as ready,
`db_pool_exhaustion` and `concurrent_modification` as
*"missing required signal X"*.

**Why:** The operator should know **before** running an
investigation which rules can possibly fire. No surprises after
the fact.

## 10 · Conflicting hypotheses — the `flaky_dependency` case

**Input:** A trace where the downstream returns 503 once, payment
retries, the retry succeeds slowly. Three rules fire with similar
confidence on disjoint evidence; none alone explains the SLA
violation the test asserted.

**Expected:** `conflicting_hypotheses` abstention. All three
candidates surfaced; engine declines to nominate one.

**Why:** The pre-trust-hardening engine confidently picked
`downstream_error` here and would have sent the engineer to inspect
the wrong layer. Detecting the conflict and abstaining is the
single highest-impact trust improvement in the codebase.

This case is the canonical mixed-signal stress test, also documented
in [CALIBRATION.md](CALIBRATION.md).

---

## How to read this gallery

Each scenario above corresponds 1-to-1 with a unit test in the
calibration benchmark. The pattern in every test:

```python
def test_scenario_X():
    ct = _ct(spans=..., logs=..., primary=...)
    result = investigate(ct)
    _no_false_high_confidence(result)        # the universal guard
    assert result.abstention is not None     # for abstention cases
    # … or assert result.primary is X        # for low-confidence cases
```

The `_no_false_high_confidence(result)` helper asserts the engine
never produced confidence ≥ 0.85 on degraded input. That single
helper is the canary — if any scenario starts violating it, the
trust contract is broken and the build fails.

## What the gallery does not cover

Cases that need a real production telemetry sample, not synthetic
fixtures:

- Truly noisy log streams where most log lines lack `trace_id`
- Duplicate spans (the same span emitted twice by parallel processors)
- Span attribute names that drift between releases
- High-cardinality business keys that cause Jaeger queries to fan out

These will populate `pilot-archive/` over the course of pilot runs.
Anonymised real-world samples are far more valuable than synthetic
ones once we have them.
