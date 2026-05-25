# Telemetry summary — `op001` (HotROD warm-up)

_Factual data only. Runner-self-pilot; no human operator. See
`feedback.md` for the warm-up disclaimer._

## Source

- Backend kind:     Jaeger (all-in-one, `jaegertracing/all-in-one:latest`)
- Workload:         `jaegertracing/example-hotrod:latest` (HotROD demo,
                    4 services + 2 datastores)
- Adapter used:     `bin/jaeger-export-to-bundles.py`
- Source command:   `curl 'http://localhost:16686/api/traces?service=<svc>&lookback=15m&limit=50'`
                    for each of `frontend customer driver route mysql redis-manual`,
                    merged by unique `traceID`
- Time window:      ~15 minute lookback (HotROD was running for ~5 min)
- Bundle file size: 1.34 MB (40 unique traces)

## Ingestion outcome

- Traces ingested:           40
- New observation events:    40
- Idempotent skips:          0
- Unmatched Loki logs:       N/A (no Loki in this setup)
- Adapter warnings:          none

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |     0 |        0%  |
| medium |    40 |      100%  |
| low    |     0 |        0%  |

All 40 observations landed in `medium` — neither high (no source has
`log_trace_correlation` because Jaeger doesn't carry logs) nor low
(propagation is clean within Jaeger).

## Per-rule match counts

| Rule | Matches |
|---|---:|
| `concurrent_modification` |  0  |
| `retry_storm`             |  0  |
| `downstream_error`        |  0  |
| `db_pool_exhaustion`      |  0  |
| `latency_vs_db`           |  0  |

All five rules abstained on all 40 traces. See "Telemetry-hygiene
findings" below for why.

## Per-abstention counts

| Abstention code | Count |
|---|---:|
| `no_primary_trace`        |   0 |
| `empty_telemetry`         |   0 |
| `no_rule_matched`         |  40 |
| `weak_evidence`           |   0 |
| `conflicting_hypotheses`  |   0 |

100% `no_rule_matched`. Honest: HotROD's telemetry shape doesn't match
the contracts of any of ARIP's five rules. The engine declined,
correctly.

## Cluster counts in digest

- Rule-grounded clusters:      0
- Abstention-grounded clusters: 1
- Total clusters:              1
- Total recurrence (sum across clusters): 40

40 traces collapse to one cluster — the fingerprint stability fix
from Phase A validation holds: `no_rule_matched` on the same
service-set produces one cluster, not 40 singletons.

## Telemetry-hygiene findings

What HotROD telemetry contains vs. what each ARIP rule needs:

| Rule | Rule needs | HotROD provides | Gap |
|---|---|---|---|
| `retry_storm` | `retry.attempt` attribute | None | HotROD does not retry at the trace level |
| `db_pool_exhaustion` | `db.pool.acquired`, `db.pool.max`, `db.pool.wait_ms` | None | HotROD's MySQL spans are bare SQL queries; no pool stats |
| `concurrent_modification` | business-key attribute (default: `order.id`) + `state.transition` events | HotROD has `customer.id` but no `state.transition` events | Different domain shape |
| `downstream_error` | ERROR span chain crossing a service boundary | HotROD's errors are isolated (Redis cache misses on `redis-manual`); they don't propagate as cross-service ERROR chains | Real but localised failures |
| `latency_vs_db` | handler operation pattern (default substring: `handle_`) + `db.system` attr on a child span | HotROD handler names are `GetDriver`, `FindDriverIDs`, `/dispatch`, etc.; mysql spans named `SQL SELECT` | **Operation-name pattern mismatch** — a `NormalizationConfig` override could activate this rule |

The single most actionable finding: **`latency_vs_db` would fire if
the operator provided a HotROD-specific config** overriding
`handler_operation_patterns` to include `/dispatch`, `/customer`,
`/route`, `Get`, `Find`. ARIP's portability contract holds — the
config knob exists; it just needs a non-demo value.

The other four rules' abstention is honest: HotROD's telemetry
genuinely does not contain the signals those rules require. No
config override would change that.
