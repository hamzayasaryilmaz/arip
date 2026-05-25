# Onboarding ARIP to a new environment

ARIP investigates Playwright failures against your existing telemetry.
The five deterministic rules read **canonical signals** — config-driven
abstractions over raw attribute names — so adapting ARIP to a new
environment means writing one config file, not new rules.

This doc walks you through:

1. The minimum viable telemetry signals.
2. Which signals each rule needs (and what happens when they are missing).
3. How to write a `NormalizationConfig` for your stack.
4. How ARIP degrades gracefully when telemetry quality is low.
5. Setups ARIP cannot meaningfully analyse — and how it tells you so.

It does **not** cover deploying ARIP to Kubernetes, replacing Docker
logs with Loki, or running multi-tenant. Those are in
[FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md) Phase 3.

## Minimum viable signals

The smallest telemetry footprint ARIP can investigate against:

| Signal                       | Why ARIP needs it                                                |
|------------------------------|------------------------------------------------------------------|
| OpenTelemetry traces         | The only way ARIP correlates failures across services            |
| Per-failure `trace_id`       | Emitted by tests via an annotation (or response header)          |
| Span `status` ERROR for 5xx  | ARIP reads `span.is_error`; otelhttp & equivalents do this for you|
| Structured (JSON) logs       | For Evidence audit; logs without `trace_id` cannot be correlated |

Without these, ARIP returns honest abstentions:
`no_primary_trace` / `empty_telemetry` / `no_rule_matched`. It does
not guess.

## Per-rule signal requirements

Each rule below lists the signal it MUST have, the signal it COULD
have for higher confidence, and what happens when the signal is
absent.

### `concurrent_modification`

| Signal                                   | Required? | Effect when absent                  |
|------------------------------------------|-----------|-------------------------------------|
| A business-key attribute on spans (`order.id` by default) | required  | Rule no-ops cleanly — no cross-trace correlation possible |
| `state.transition` span events            | required  | Rule no-ops cleanly                 |
| Two traces touching the same key, overlapping in time | required  | Rule no-ops                         |
| WARN logs mentioning unexpected state    | optional  | Confidence drops from 0.92 → 0.60   |

Config knobs: `business_keys`, `state_transitions.*`.

### `retry_storm`

| Signal                                  | Required? | Effect when absent                                  |
|-----------------------------------------|-----------|-----------------------------------------------------|
| `retry.attempt` attribute on retry spans| required  | Rule no-ops cleanly                                 |
| ≥ 2 attempts in same trace + same op    | required  | Rule no-ops                                         |
| `retry.backoff_ms`                      | optional  | Used to detect exponential pattern (+0.04 confidence)|
| `retry.max_attempts`                    | optional  | Used to detect exhaustion (+0.03)                   |
| `retry.reason`                          | optional  | Used to detect persistent vs transient (+0.05)      |
| `retry.policy`                          | optional  | Cosmetic; included in suggested next step           |

Config knobs: `retry.*`.

### `downstream_error`

| Signal                                  | Required? | Effect when absent                                  |
|-----------------------------------------|-----------|-----------------------------------------------------|
| ERROR span status across two services   | required  | Rule no-ops                                         |
| `http.response.status_code` attribute   | optional  | Used to phrase "HTTP 503" in description            |
| ERROR-level logs from downstream         | optional  | Surfaced as corroborating evidence                  |

Config knobs: `http_status_attrs`.

### `db_pool_exhaustion`

| Signal                                                            | Required? | Effect when absent                                |
|-------------------------------------------------------------------|-----------|---------------------------------------------------|
| `db.pool.acquired` + `db.pool.max` on a span                      | required  | Rule no-ops cleanly                               |
| `db.pool.wait_ms`                                                 | required  | Rule needs to know how long the acquire waited    |
| `db.pool.empty_acquires_total`                                    | optional  | Used as an "is this really saturation" tiebreaker |
| A "DB acquire" span (configurable op names)                       | optional  | Used to phrase evidence                           |

Config knobs: `db.pool.*`.

### `latency_vs_db`

| Signal                              | Required? | Effect when absent                            |
|-------------------------------------|-----------|-----------------------------------------------|
| Span `duration_us`                  | required  | Rule no-ops                                   |
| `db.system` attribute on DB spans   | required  | (or matching operation-name pattern)          |
| Operation-name pattern for handlers | required  | Configurable; defaults to `handle_` substring |

Config knobs: `db.system_attr`, `db.operation_patterns`, `handler_operation_patterns`.

## Writing your config

Start from the defaults:

```bash
cp arip-core/configs/demo.yaml configs/my-prod.yaml
```

Override only the fields whose names differ from the demo. A field you
do not touch keeps the built-in default. A field set to an empty list
**disables** the corresponding feature gracefully.

Example: a Spring-style application using OTel auto-instrumentation
might look like:

```yaml
name: my-prod

business_keys:
  - account.id
  - tenant.id

retry:
  attempt_attr:       http.retry.attempt_number
  max_attempts_attr:  http.retry.max
  backoff_attr:       http.retry.backoff.delay_ms
  reason_attr:        http.retry.cause

handler_operation_patterns:
  - "Controller#"      # Spring controllers
  - "Resource."        # JAX-RS resources

state_transitions:
  event_name: domain.event.state_changed
  from_attr:  domain.from_state
  to_attr:    domain.to_state

# Pool stats, HTTP status, db.system — accept the defaults, they
# match the OTel semantic conventions.
```

Run with:

```bash
uv run arip investigate report.json --config configs/my-prod.yaml --out reports/
```

ARIP prints which config it loaded and which canonical signals are
enabled vs disabled before running. A typical onboarding session is
"run, see what abstains, add the missing signal, run again".

## Environment quality scoring

Every investigation report now includes a quality assessment.  The
score is computed deterministically from the telemetry that ARIP
actually saw — no rule's behaviour depends on it. Its only job is
to tell you, in one number, whether the engine was working with rich
or thin signals.

Scoring bands:

| Band         | Score range  | What it means for reading the report                                         |
|--------------|--------------|------------------------------------------------------------------------------|
| `high`   🟢  | ≥ 0.80       | Most signals present. Primary hypotheses can be acted on.                    |
| `medium` 🟡  | 0.50 – 0.79  | Some signals missing. Cross-check the primary against the alternatives.      |
| `low`    🔴  | < 0.50       | Materially incomplete telemetry. ARIP may abstain often; when it produces a primary, treat as a hint, not a conclusion. |

Scored coverages (each is "applicable obs satisfying contract / applicable obs seen"):

- `primary_trace_present` — the failing test's trace actually reached Jaeger
- `propagation_health` — non-root spans have resolvable `parent_span_id`
- `error_status_consistency` — HTTP-4xx/5xx spans also have OTel ERROR status
- `business_key_on_entry` — entry-point spans tagged with a configured business key
- `retry_metadata_completeness` — retry spans carrying full metadata when any retry is present
- `log_trace_correlation` — log entries carrying `trace_id`

Signals that don't apply to this telemetry (e.g. retry metadata in a
single-attempt trace) are excluded from the average — they do not
penalise the score.

## Quick preflight check

Before relying on ARIP in a new environment, run:

```bash
uv run arip preflight tests/playwright/playwright-report.json
```

This produces a one-shot diagnostic:

- environment quality score + band
- per-signal coverage table
- per-rule readiness checklist (✓ "would fire" vs ✗ "missing required signal X")
- specific findings (with severity)

No reports are written, nothing in the memory store is touched.
Preflight is read-only.

## Per-rule contracts

Each shipped rule declares its required and optional signals in code
(`arip_core/quality/contracts.py`). The contracts are surfaced by
`arip preflight` and also serve as the regression spec — a refactor
that quietly relaxes one of these is a trust-layer regression and is
expected to fail the [calibration benchmark](../arip-core/tests/test_calibration_benchmark.py).

| Rule                       | Required canonical signals                       | Falls back to                                            |
|----------------------------|--------------------------------------------------|----------------------------------------------------------|
| `concurrent_modification`  | `business_keys` + `state_transitions`            | silent no-op                                             |
| `retry_storm`              | `retry_attempt`                                  | silent no-op                                             |
| `downstream_error`         | `span_error_status` + `service_boundary`         | silent no-op                                             |
| `db_pool_exhaustion`       | `db_pool_stats` (acquired + max + wait_ms)       | silent no-op — DELIBERATELY strict, no false positives   |
| `latency_vs_db`            | `handler_span_identifiable` + `db_child_span`    | silent no-op                                             |

Required signals are non-negotiable — if your telemetry doesn't emit
them, the rule will not fire (and quality will say so explicitly).
Optional signals are confidence boosters; their absence is fine.

## Graceful degradation

ARIP's contract is: **when a signal is missing, the rule no-ops; the
engine surfaces abstention rather than guessing.** Here is how that
looks across signal-quality tiers:

| Telemetry quality                         | Expected ARIP behaviour                              |
|-------------------------------------------|------------------------------------------------------|
| Full demo-equivalent telemetry            | Primary hypothesis with high confidence              |
| Missing pool stats only                   | `db_pool_exhaustion` silent; other rules unaffected  |
| Missing retry metadata                    | `retry_storm` silent; downstream_error may still fire |
| Missing business keys                     | `concurrent_modification` silent; no cross-trace lookups |
| Missing structured logs                   | Confidence boosts that rely on logs are not applied; rules still fire on span evidence alone |
| Trace not flushed to backend yet          | Engine returns abstention `no_primary_trace`         |
| Mixed signals across rules (ambiguity)    | Engine returns abstention `conflicting_hypotheses`   |
| No rule signature matched                 | Engine returns abstention `no_rule_matched`          |

The combination of these means: **the worse your telemetry, the more
ARIP abstains.** This is the design — silent abstention is far less
dangerous than confident-but-wrong RCAs. The
[CALIBRATION](CALIBRATION.md) doc explains the trust contract in
detail.

## Setups ARIP cannot meaningfully analyse

If your environment is missing all of these, ARIP will abstain on
nearly every failure:

- No OpenTelemetry tracing at all (or tracing without `trace_id`
  propagation across services)
- No structured logs (only opaque text)
- Tests that do not annotate the `trace_id` of the operation they
  exercised

In that case the answer is **not to add more rules** — the answer is
to fix the underlying telemetry hygiene. ARIP gives you a punch list
of which canonical signals it could not find for each abstention.

## The portability claim, demonstrated

The repository ships two configs:

- [`configs/demo.yaml`](../arip-core/configs/demo.yaml) — the demo
  stack's conventions
- [`configs/foreign-conventions.yaml`](../arip-core/configs/foreign-conventions.yaml)
  — a synthetic example with deliberately-different attribute names

The end-to-end test in `tests/test_canonical.py::test_retry_storm_fires_with_foreign_attribute_names`
and the equivalent cross-config portability proof both verify that
the **same rule** fires with the **same conclusion** against
telemetry that uses **completely different attribute names**, just by
swapping the config.

That is the portability contract. If a rule depends on a hardcoded
attribute key, it fails one of those tests — caught in code review.

## What is intentionally not configurable

Some things you cannot turn off via config because they would
undermine the trust layer:

- Evidence-audit (every cited reference must exist in telemetry)
- Abstention pathways (no_primary_trace, weak_evidence, conflicting_hypotheses, no_rule_matched)
- Confidence floors and ceilings used by the conflict detector

Those are core engine behavior. The config controls the **input**, not
the **reasoning**.

## Next

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — module-level overview
- [docs/INVESTIGATION_RULES.md](INVESTIGATION_RULES.md) — rule registry
- [docs/CALIBRATION.md](CALIBRATION.md) — trust contract + benchmark
- [docs/FAILURE_MATRIX.md](FAILURE_MATRIX.md) — per-scenario telemetry signatures
- [arip-core/configs/](../arip-core/configs/) — example configs
