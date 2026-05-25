# Investigation Rules

Every rule is a pure function of `CorrelatedTelemetry`. Given the same
telemetry, it produces the same `Hypothesis` output. No LLM, no
randomness, no clocks.

## Rule registry (shipped)

| rule_id                    | Detects                                                | Required telemetry                                                              | Confidence signals (cumulative)                                                                 | Abstention behavior                                                          |
|----------------------------|--------------------------------------------------------|---------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| `concurrent_modification`  | Two operations mutating the same business entity in overlapping time | spans with `order.id` attribute across 2+ traces; `state.transition` span events on both sides | 0.60 baseline → +0.20 if both sides emit `state.transition` → +0.12 if WARN log corroborates    | Single-trace; no time overlap; only one side performed a transition (read on the other) |
| `retry_storm`              | Same logical operation retried 2+ times in one trace, with deterministic retry metadata | 2+ spans in the same trace, same `operation_name`, each carrying `retry.attempt` | 0.80 base → +0.05 consistent `retry.reason` → +0.04 exponential backoff detected → +0.03 budget exhausted → +0.02 ERROR logs | No `retry.attempt` attribute; only one attempt; attempts on different operations |
| `downstream_error`         | ERROR chain bottoming out in a different service than where it surfaced | 2 ERROR-status spans, parent/child, on different `service_name`                | 0.90 (constant)                                                                                 | No cross-service ERROR pair                                                  |
| `db_pool_exhaustion`       | Database connection pool saturated; latency above the DB query | Span with `db.pool.*` attribute family AND (`db.pool.acquired ≥ db.pool.max` OR `db.pool.wait_ms ≥ 100`) | 0.80 base → +0.05 healthy-query contrast span → +0.05 WARN log → +0.03 `empty_acquires_total > 0` | Symptom looks like a slow acquire span but `db.pool.*` attributes missing — does NOT speculate |
| `latency_vs_db`            | Application-layer latency, not the database             | Handler span (`*handle_*`) with duration ≥ 50 ms AND at least one `db.*` child; ratio ≥ 10× | 0.85 (constant)                                                                                 | No DB child; ratio below threshold; handler too short                        |

The rule files are in [arip_core/engine/rules/](../arip-core/arip_core/engine/rules/).
Each rule's full source is short (~100 LoC) and reads as the
narrative descriptions below.

Add or change rules by editing only those files + a matching unit test
in [tests/test_*_rule.py](../arip-core/tests/) — no other layer needs
to know.

## Rule contract

```python
class Rule(Protocol):
    rule_id: str
    def evaluate(self, ct: CorrelatedTelemetry) -> list[Hypothesis]: ...
```

A `Hypothesis` MUST carry at least one `Evidence` record. Hypotheses
without supporting evidence are dropped by the scoring layer
(`arip_core/engine/scoring.py`) so the engine never reports
unsupported claims.

## Current rules

### `webhook_race` ([arip_core/engine/rules/webhook_race.py](../arip-core/arip_core/engine/rules/webhook_race.py))

Triggers when **both** are true:

1. A `webhook.process` span exists with `anomaly.webhook_early=true`
   (the webhook arrived while the order was still in `pending`).
2. A `checkout.process` span exists with `anomaly.webhook_race=true`
   (checkout discovered the order was already paid when it finished
   reserving).

Severity `high`, confidence 0.95. Suggests gating the `paid` transition
on a successful reservation.

### `downstream_error` ([arip_core/engine/rules/downstream_error.py](../arip-core/arip_core/engine/rules/downstream_error.py))

Walks the span tree looking for an `ERROR` span whose nearest descendant
in a **different service** is also `ERROR`. The lowest such error is
the originating service. The rule also surfaces any `failure.injected.*`
attributes so injected chaos failures are clearly labelled in the
report.

Severity `high`, confidence 0.90.

### `latency_vs_db` ([arip_core/engine/rules/latency_vs_db.py](../arip-core/arip_core/engine/rules/latency_vs_db.py))

Compares each handler span to its `db.*` children. If the handler took
more than 50ms **and** more than 10× the total DB time, the latency is
above the database layer. Stops engineers from chasing "the DB is slow"
ghosts.

Severity `medium`, confidence 0.85.

### `db_pool_exhaustion` ([arip_core/engine/rules/pool_exhaustion.py](../arip-core/arip_core/engine/rules/pool_exhaustion.py))

Looks for `db.pool.*` attributes on any span. Fires when either:

- `db.pool.acquired` ≥ `db.pool.max` (pool fully utilised at the
  moment of the span), or
- `db.pool.wait_ms` ≥ 100 (the caller waited for a connection).

Cites the saturated acquire span, contrasts it with a healthy
`db.decrement_stock` query span ("query is fast — pool is the wait"),
and surfaces upstream errors and WARN logs as corroboration. Severity
`high`, confidence 0.80–0.95 depending on corroborating signal
strength.

**Strict evidence gating.** If a slow acquire-like span exists but
carries no `db.pool.*` attributes, the rule does NOT fire. The
investigation engine then abstains at the report level rather than
guessing. The reason this rule is so narrow: pool exhaustion has a
specific telemetry contract — without it, the symptom (slow DB-side
span) is consistent with many other failure modes.

**Why it doesn't collide with `latency_vs_db`.** In pool exhaustion
the handler latency lives **inside** the `db.acquire_connection` span,
which is itself a `db.*` span. The handler-to-DB ratio is near 1:1,
which is below `latency_vs_db`'s 10× threshold. Conversely, on a
genuine application-side sleep (slow_query), the handler-to-DB ratio
is high and no pool attributes are emitted, so `latency_vs_db` fires
and `db_pool_exhaustion` does not.

### `retry_storm` ([arip_core/engine/rules/retry_storm.py](../arip-core/arip_core/engine/rules/retry_storm.py))

Reconstructs the retry chain for the same logical operation in a
single trace. Looks for spans carrying `retry.attempt` metadata,
groups them by `(trace_id, operation_name)`, and fires when 2 or more
attempts are observed for the same chain.

What it cites:

- Each attempt as a separate span Evidence with its `retry.attempt`,
  `retry.backoff_ms`, and `retry.reason`
- The downstream error span that triggered the retries (proves the
  downstream is the root cause; retries are the symptom)
- ERROR-level logs from the trace

What it reports:

- Number of attempts and amplification factor (1 logical request →
  N downstream calls)
- Whether backoff was exponential (detected from the ratio of
  consecutive backoffs)
- Whether all attempts shared the same `retry.reason` (consistent
  downstream condition vs. flapping)
- Whether the retry budget was exhausted

Severity `high`, confidence 0.80–0.95 depending on corroborating
signal strength.

**Strict evidence gating.** The rule requires the `retry.attempt`
attribute. A trace that shows many error spans without that metadata
is *downstream_error* territory, not *retry_storm* — even if you
suspect retries are happening, without the metadata we cannot prove
the chain linkage.

**Why it doesn't collide with `downstream_error`.** Both rules can
fire on the same trace: a retry storm always contains a downstream
error. The retry storm wins at scoring because it has a more
specific signature (`retry.attempt` linkage is a stronger signal than
"two ERROR spans in different services"). `downstream_error` is then
surfaced as an alternative hypothesis — informative, since it
identifies the actual originating service.

## Adding a new rule

1. Create `arip_core/engine/rules/<name>.py` with a class exposing
   `rule_id` and `evaluate(ct)`.
2. Register it in `default_rules()` in
   `arip_core/engine/hypothesis.py`.
3. Add a smoke test in `tests/`.

Rules should:

- Read **only** from `CorrelatedTelemetry`. Do not call external services.
- Produce at most a handful of hypotheses per call.
- Cite specific span IDs / log lines / DB rows in `Evidence`.
- Set `severity` and `confidence` honestly; don't pad to look impressive.

Rules should NOT:

- Make probabilistic guesses about the root cause.
- Call an LLM.
- Modify any input.
- Throw — let `investigate()` catch and log, so one broken rule does
  not kill the pipeline.
