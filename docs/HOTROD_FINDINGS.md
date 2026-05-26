# HotROD findings — Phase A observe-mode against an unknown system

Permanent record of what observe-mode did when pointed at a real
OpenTelemetry-emitting OSS system (Jaeger HotROD demo) the engine
had never seen. Telemetry used as-is — no naming cleanup, no
canonical attribute injection, no telemetry repair of any kind.

This is **not** a success story. It is honest validation, and the
honest report includes things that did not work.

Setup, run details, and surface-fix actions: see
[UNKNOWN_SYSTEM_VALIDATION.md](UNKNOWN_SYSTEM_VALIDATION.md) and
[observe-pilot-archive/op001/](observe-pilot-archive/op001/).

## 1. Portability evidence

The same engine + same adapters + default config ingested 40
HotROD traces across 6 services without code modification.
`bin/jaeger-export-to-bundles.py` consumed Jaeger's native JSON
(typed tags `int64`/`string`/`bool`, `processes` map for
service-name lookup, `CHILD_OF` references) with zero adapter
warnings.

**What this proves:** the operator-side adapter, the observation
pipeline, and the cluster store all work against an OTel-instrumented
system that has nothing to do with the demo. No demo-specific
assumption leaked into the ingestion path.

**What this does NOT prove:** that the rule contracts are similarly
portable. They aren't, fully. See section 4.

## 2. Boundedness evidence

40 traces, 6 services, 8 distinct operation names → **1 cluster.**

| Input | Cluster output |
|---|---|
| 40 trace bundles | 1 abstention cluster (`no_rule_matched × 40`) |
| 6 services in the cluster | All 6 present in `services` field |
| 8 operation names | Top 4 shown explicitly + "(+4)" elision |

The fingerprint stability fixes from
[PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) Appendices A
(evidence-multiplicity → set) and B (abstention-fingerprint
operation-name removal) **both held against real telemetry**:
no path-parameter cardinality splits, no multiplicity-driven
splits, no cluster explosion.

Digest fit comfortably within ~30 lines.

## 3. Abstention correctness

100% of observations landed in `no_rule_matched`. Per-rule analysis:

| Rule | HotROD signal present? | Verdict |
|---|---|---|
| `retry_storm` | No `retry.attempt` attribute | Honest abstention — HotROD doesn't retry at trace level |
| `db_pool_exhaustion` | No `db.pool.*` attributes | Honest abstention — bare SQL spans, no pool stats |
| `concurrent_modification` | No `state.transition` events | Honest abstention — different domain shape |
| `downstream_error` | Errors present but isolated (Redis cache misses on `redis-manual`); no cross-service ERROR chain | Honest abstention — errors don't propagate as the rule's contract requires |
| `latency_vs_db` | Has handler-like spans + `mysql` child, but handler names don't match default pattern | **Honest abstention given default config** — would fire with override |

**Headline outcome:** zero false-high-confidence rule clusters on
telemetry the engine had never seen. The trust contract held under
genuinely-novel input. The engine did not invent findings to fill
the silence.

## 4. Onboarding friction (real, not glossed)

Things that did not "just work" and would have wasted a real
operator's time:

### Friction A — Default handler pattern is demo-specific

`arip-core/configs/demo.yaml` ships
`handler_operation_patterns: ['handle_']`. HotROD handlers are
`/dispatch`, `/customer`, `/route`, `GetDriver`, `FindDriverIDs`.
None match. Consequence: `latency_vs_db` silently abstained on
every HotROD trace despite the underlying telemetry supporting it.

A real operator would need to:
1. Notice from the digest that handler operation names look
   non-demo
2. Read `arip-core/configs/demo.yaml` to find the knob
3. Author a `configs/hotrod.yaml` overriding `handler_operation_patterns`
4. Re-run with `--config`

Documented in [OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md)
pre-pilot checklist with common-override examples (Spring
`Controller#`, Go HTTP `/api/`, gRPC `Service/`). The engine knob
already existed — the docs gap was the friction.

### Friction B — Self-audit hint block didn't cover the 100%-abstention case

`bin/observe-self-audit.sh`'s closing hints had 4 interpretation
bullets, none covering "100% `no_rule_matched`" — which was the
actual HotROD outcome and a common honest case for any non-demo
system. The runner had to read OBSERVE_MODE.md to know that
abstention can be the correct answer, not a bug.

Fixed with a one-line addition to the hint block.

### Friction C — Jaeger image tag drift

`jaegertracing/all-in-one:1.62` (a commonly-cited tag in docs and
tutorials) no longer exists on Docker Hub. `:latest` worked.
INGESTION_GUIDE.md does not currently warn about this. Minor; a
real operator would notice in 30 seconds and fix.

### Friction D — Per-service Jaeger export is the natural pattern

To get all relevant traces, the runner had to query
`?service=<svc>&lookback=15m&limit=50` once per service then merge
by `traceID`. Returns are large (each service returned 2 MB of
duplicate trace data because services participate in each other's
traces). A single `?service=frontend` query would have caught most
useful traces, but discovering this is empirical.

[INGESTION_GUIDE.md](INGESTION_GUIDE.md) Workflow 1 says "Pull a
window's worth of traces from Jaeger" with `?service=payment-service`
— but for multi-service systems where you don't know the entry
service, this is incomplete advice. Worth a follow-up doc tweak
(not done in this iteration; out-of-scope for op001).

## 5. Telemetry pathology (observed, not speculated)

Concrete pathologies seen in real HotROD telemetry:

| Pathology | Where observed | Effect on observe-mode |
|---|---|---|
| Handler operation names use HTTP path / RPC method format, not `handle_*` substring | All 6 services | `latency_vs_db` abstains; config override fixes |
| MySQL spans named `SQL SELECT`, no `db.system` attribute | `mysql` service | `db.system_attr` config check fails; potentially affects DB rules |
| No `db.pool.*` attributes | `mysql` service | `db_pool_exhaustion` abstains (correct — no pool in this app) |
| Cross-service errors are NOT chained — `redis-manual` errors stay local | Multiple traces | `downstream_error` abstains (correct — no actual cross-service error chain to detect) |
| No log entries in Jaeger export at all | All services | `log_trace_correlation` coverage drops to 0; quality band → medium |
| `customer.id` attribute present on `customer` service spans | `customer` service | Business-key potential, but no `state.transition` events anywhere |
| Operation names include both HTTP-style (`/dispatch`) and Go-method-style (`GetDriver`, `FindDriverIDs`) within the same trace | Most traces | Cluster operation-sample column shows the heterogeneity honestly |

Three of these (handler pattern, lack of db.pool stats, lack of
cross-service ERROR propagation) are about **what HotROD chose to
instrument**, not bugs. Two (no logs in Jaeger, MySQL span naming)
are about **what Jaeger emits**, not HotROD. None are ARIP
defects.

## The non-negotiable statement

> **Zero false-high-confidence outcomes on telemetry the engine had
> never seen.**

This is the single most important validation finding from op001.
40 traces ingested, 0 rule clusters fabricated, 0 trust-layer
escapes. Every trace either matched a rule's contract honestly or
landed in `no_rule_matched` honestly.

This sentence is also the easiest to misread as a success story.
It is not. The honest reading is:

- The trust contract was given an opportunity to fail loudly on
  unknown input. It didn't.
- But the engine also produced **zero useful rule clusters** for
  HotROD. The bound was reached by being silent, not by being
  insightful.
- An operator running observe-mode on HotROD with defaults would
  get a digest that correctly says "I have no rule that applies."
  That is honest but not directly actionable.
- The path to useful clusters on HotROD requires telemetry
  hygiene (cross-service error propagation, log_trace_correlation)
  AND a config override (handler pattern). The first is HotROD's
  problem; the second is a known portability knob.

The trust outcome is the more important one. A digest that
abstains honestly under unknown input is the precondition for
trustworthy clusters when telemetry does fit. Without the first,
the second is unsafe.

## What this iteration explicitly did not produce

In keeping with observe-mode discipline:

- No candidate test (Phase A capability boundary)
- No new rule (frozen; would require Phase 2 entry gate clearance)
- No telemetry repair on the HotROD side (`olduğu gibi` test)
- No fictional operator quotes (op001 archive carries explicit
  "NO HUMAN OPERATOR" disclaimers)
- No engine code change (only docs + one CLI hint line + one
  `.gitignore` exception)
- No `op001` rolled into Phase 2 entry-gate counts

## Cross-references

- [UNKNOWN_SYSTEM_VALIDATION.md](UNKNOWN_SYSTEM_VALIDATION.md) —
  full setup, run, surface-fix narrative
- [observe-pilot-archive/op001/](observe-pilot-archive/op001/) —
  verbatim archive (digest + telemetry-summary + usability-findings
  + NO-HUMAN-OPERATOR disclaimers)
- [OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md) — pre-pilot
  checklist (now includes naming-convention check from Friction A)
- [TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) — broader
  catalogue (these op001 findings are pre-pilot, not yet eligible
  for the catalogue's pilot-sourced section)
- [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) — prior synthetic
  noise + real-export-shape validation
