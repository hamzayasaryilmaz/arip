# Telemetry summary — `op002` (OpenTelemetry Demo)

_Factual data only. Runner-self-pilot; no human operator. See
`feedback.md` for the warm-up disclaimer and
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
for the cross-system narrative._

## Source

- Backend kind:     Jaeger v2 (embedded in OTel Demo's compose.observability.yaml)
- Workload:         `open-telemetry/opentelemetry-demo` (CNCF
                    reference), `compose.yaml + compose.observability.yaml`,
                    27 services across Go, .NET, Java, JS, Python, Rust
- Adapter used:     `bin/jaeger-export-to-bundles.py`
- Source command:   `curl 'http://localhost:60597/jaeger/ui/api/traces?service=<svc>&lookback=10m&limit=50'`
                    for each of `frontend cart checkout payment recommendation product-catalog shipping ad currency email quote`,
                    merged by unique `traceID`
- Time window:      ~10 min lookback (built-in load-generator was running)
- Bundle file size: 3.5 MB (291 unique traces)

## Ingestion outcome

- Traces ingested:           291
- New observation events:    291
- Idempotent skips:          0
- Unmatched Loki logs:       N/A (no Loki source in this run)
- Adapter warnings:          none

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |     0 |        0%  |
| medium |   291 |      100%  |
| low    |     0 |        0%  |

All 291 observations landed in `medium`.

## Per-rule match counts

| Rule | Matches |
|---|---:|
| `concurrent_modification` |  0  |
| `retry_storm`             |  0  |
| `downstream_error`        |  0  |
| `db_pool_exhaustion`      |  0  |
| `latency_vs_db`           |  0  |

Zero rule matches. This run was against **default (healthy)** OTel
Demo traffic — no feature flags enabled. Honest outcome: no rule's
contract triggered.

A follow-up pilot with `productCatalogFailure` /
`cartServiceFailure` / `recommendationServiceCacheFailure` enabled
via flagd would be the natural test of whether rules fire correctly
when telemetry has the right shape.

## Per-abstention counts

| Abstention code | Count |
|---|---:|
| `no_primary_trace`        |   0 |
| `empty_telemetry`         |   0 |
| `no_rule_matched`         | 291 |
| `weak_evidence`           |   0 |
| `conflicting_hypotheses`  |   0 |

100% `no_rule_matched`. Honest: every trace either had no anomaly
shape or had one the engine has no rule for. The engine declined,
correctly.

## Cluster counts in digest

- Rule-grounded clusters:      0
- Abstention-grounded clusters: 8 (post-fix; was 23 pre-fix)
- Total clusters:              8
- Total recurrence:            291

## Defect caught during this run

**`_abstention_fingerprint` used the full transitive service-set**,
causing 23 distinct abstention clusters from 291 traces in this
16-service mesh. Fixed by changing the fingerprint to use only
entry-point services. Post-fix: 8 clusters.

Full narrative + regression test in
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
"Defect 1".

## Telemetry-hygiene findings

What OTel Demo's telemetry contains vs. what each ARIP rule needs:

| Rule | Why no fire on healthy OTel Demo traffic |
|---|---|
| `retry_storm` | No `retry.attempt` on healthy traffic; retries only fire under fault injection |
| `db_pool_exhaustion` | OTel Demo doesn't emit `db.pool.*` attributes |
| `concurrent_modification` | No `state.transition` events |
| `downstream_error` | No ERROR span chains on healthy traffic |
| `latency_vs_db` | Operation names like `oteldemo.CartService/GetCart` don't match default `handle_` substring; needs `handler_operation_patterns` override |

The single most actionable finding: **OTel Demo's handler operation
names need a `handler_operation_patterns` override** for the
`latency_vs_db` rule to attempt to fire. Same pathology as HotROD
(op001); seen twice now → strengthens
[OBSERVE_PILOT_KIT.md](../../OBSERVE_PILOT_KIT.md) pre-pilot
naming-convention check.
