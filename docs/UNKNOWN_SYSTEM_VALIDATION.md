# Unknown-system validation — HotROD (op001 warm-up)

The first run of ARIP observe-mode against a real OpenTelemetry-emitting
OSS system the engine had never seen. Telemetry was used **as-is** —
no naming cleanup, no canonical attribute injection, no telemetry
"repair" of any kind.

Honest verdict up front: **portability held, trust contract held,
bounded output, zero false confidence.** Two real surface-area
findings, one applied as a narrow docs fix, one applied as a
one-line CLI hint tweak. No engine change.

## What was actually tested

| Element | Setting |
|---|---|
| System under test | `jaegertracing/example-hotrod:latest` (HotROD demo) |
| Telemetry backend | `jaegertracing/all-in-one:latest` (Jaeger, OTLP enabled) |
| Adapter | `bin/jaeger-export-to-bundles.py` (operator-side, unchanged) |
| ARIP config | Default (`arip-core/configs/demo.yaml`) — no overrides |
| Traffic | ~40 HTTP requests across 4 customer IDs, both concurrent bursts and sequential |
| Traces ingested | 40 unique trace_ids spanning 6 services |
| Engine | Unchanged 5-rule deterministic engine + abstention layer |

Both containers running, traffic generated, traces pulled with
plain `curl` against Jaeger's HTTP API, fed straight into the
existing adapter, observed without modification. The whole loop ran
in ~5 minutes.

## What the digest produced (verbatim)

```
## Run summary

- traces observed:           40
- new events:                40
- idempotent skips:           0
- quality band distribution: medium=40
- abstentions:               no_rule_matched=40

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

| abstention      | recurrence | services                                                | operations                              |
|-----------------|-----------:|---------------------------------------------------------|-----------------------------------------|
| no_rule_matched |         40 | customer, driver, frontend, mysql, redis-manual, route  | /customer, /dispatch, /route, FindDriverIDs (+4) |
```

40 traces → 1 cluster. The fingerprint stability fixes from
[PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) Appendices A and B
both held: no multiplicity-driven splits, no path-parameter
cardinality splits.

## Headline findings

### Finding 1 (Major) — Default handler-pattern config is demo-specific

ARIP's default config sets `handler_operation_patterns: ['handle_']`.
HotROD handler names are `/dispatch`, `/customer`, `/route`,
`GetDriver`, `FindDriverIDs` — none contain `handle_`. Consequence:
`latency_vs_db` rule cannot identify entry-point spans and abstains
on every HotROD trace.

This is **not** an engine defect — the config knob exists for
exactly this reason. It IS a documentation gap: a pilot operator
running observe-mode against a non-demo system has no warning that
the default config has demo-specific naming until they read the
rule contracts or compare the digest's operations column to the
default pattern.

**Action taken:** [docs/OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md)
pre-pilot checklist now includes a naming-convention check with
common-override examples (Spring `Controller#`, Go HTTP `/api/`,
gRPC `Service/`). No engine change.

### Finding 2 (Minor) — Self-audit hint block missing 100%-abstention case

`bin/observe-self-audit.sh`'s closing interpretation block had 4
hints but none covered "100% `no_rule_matched`" — which is exactly
the HotROD case and a common honest-abstention scenario for any
non-demo system.

**Action taken:** Added one bullet to the hint block pointing at
the `NormalizationConfig` override path. One-line CLI wording
change. No engine change.

### Other observations (not findings)

- **Cluster stability:** 40 traces, 6 services, 8 distinct
  operation names → 1 cluster. The stress-test bound from
  [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) held against real
  telemetry.
- **No false confidence:** zero rule-grounded clusters produced.
  Every trace honestly landed in `no_rule_matched`. The engine did
  not invent findings to fill the silence.
- **Quality band realism:** 100% medium. Higher than `low`
  (propagation is clean), but lower than `high` (no log
  correlation — Jaeger doesn't carry logs).
- **Adapter robustness:** `bin/jaeger-export-to-bundles.py` handled
  Jaeger's typed-tag format (`int64`, `string`, `bool`), the
  `processes` map for service-name lookup, and `CHILD_OF`
  references — no errors, no warnings, no manual coercion needed.

## What HotROD's telemetry tells us about ARIP's 5 rules

| Rule | HotROD fit | Why |
|---|---|---|
| `retry_storm` | N/A | HotROD doesn't retry; no `retry.attempt` emitted by design |
| `db_pool_exhaustion` | N/A | HotROD's MySQL spans are bare SQL, no pool stats |
| `concurrent_modification` | N/A | No `state.transition` events; different domain shape |
| `downstream_error` | N/A | HotROD's errors are isolated (Redis cache misses); no cross-service ERROR chain |
| `latency_vs_db` | **Would fit with config override** | Has handler spans + `mysql` child spans; just needs `handler_operation_patterns` override |

The pattern: 4 of 5 rules abstain because the telemetry genuinely
lacks the required shape — that's honest. 1 rule abstains because
of a known portability knob — fixable with a config override; the
operator would discover this through the digest's operations column
and the new docs pointer.

A second pilot pass on HotROD with a `configs/hotrod.yaml` providing
`handler_operation_patterns: ['/dispatch', '/customer', '/route', 'Get', 'Find']`
would likely produce one rule-grounded `latency_vs_db` cluster. That
experiment is deferred — the first pilot's job was to capture the
as-is finding, not to optimize.

## Trust-contract verdict

The single most important question for an unknown-system validation:

> *Did ARIP produce any confidently-wrong cluster on a system it
> had never seen?*

**No.** Every trace landed in `no_rule_matched` — the engine's
"I have no rule for this" abstention. The trust contract requires
exactly this behavior. A digest full of fabricated rule clusters
on HotROD would have been a P0 trust regression.

## What this validation did NOT do

In keeping with observe-mode discipline:

- **No candidate test generation** — Phase A capability boundary
- **No telemetry repair** — HotROD's traces were converted but not
  enriched, augmented, or smoothed
- **No new rule** — temptation to add a `hotrod_*` rule was
  ignored; rules stay frozen until Phase 2 entry gate clears
- **No fake operator feedback** — `op001/feedback.md` and
  `op001/operator-notes.md` are explicit "NO HUMAN OPERATOR"
  disclaimers; no fictional engineer quotes were produced
- **No `op001` rolled into Phase 2 entry-gate counts** — the
  warm-up disclaimer is unmistakable; only `op002+` (real
  engineers) count
- **No engine code changes** — only docs (`OBSERVE_PILOT_KIT.md`)
  and a one-line CLI wording tweak (`observe-self-audit.sh`)

## What the next pilot (op002) inherits from this one

- Confirmed pilot machinery works end-to-end on an unknown system
  (5-minute setup → digest in hand)
- Confirmed the adapter handles real Jaeger JSON without
  modification
- Confirmed trust contract holds under genuinely-novel telemetry
- One known portability gotcha now documented in the pre-pilot
  checklist (`handler_operation_patterns` defaults to demo-only)
- One known interpretive ambiguity now resolved in self-audit
  output (100% abstention isn't necessarily a bug)

`op002` is the first **real** pilot — recruited engineer, their
own CI/staging telemetry, verbatim feedback. See
[OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md).

## Files added / changed by this iteration

- `docs/observe-pilot-archive/op001/` — full archive with NO-HUMAN-OPERATOR
  labels on `feedback.md` and `operator-notes.md`, factual data in
  `telemetry-summary.md`, runner observations in `usability-findings.md`
- `docs/UNKNOWN_SYSTEM_VALIDATION.md` — this document
- `docs/OBSERVE_PILOT_KIT.md` — naming-convention check added to
  pre-pilot checklist (Finding 1 fix)
- `bin/observe-self-audit.sh` — 100%-abstention hint added to
  closing block (Finding 2 fix)

Test count unchanged (145/145). No engine code touched.
