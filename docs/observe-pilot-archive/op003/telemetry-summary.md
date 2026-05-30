# Telemetry summary — `op003` (Grafana Tempo single-binary)

_Factual data only. Runner-self-pilot; no human operator. See
`feedback.md` for the warm-up disclaimer and
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
for the cross-system narrative._

## Source

- Backend kind:     Grafana Tempo v3.0.0 (single-binary mode)
- Workload:         `grafana/tempo` `example/docker-compose/single-binary/`
                    — Tempo + Grafana + Prometheus + Alloy + Vulture + k6-tracing
                    (synthetic OTel traffic generators)
- Adapter used:     `bin/tempo-export-to-bundles.py` (newly written for op003)
- Source command:   `curl 'http://localhost:3200/api/search?tags=&limit=30'` for
                    trace IDs; then `curl 'http://localhost:3200/api/traces/<id>'`
                    bulk-fetched into JSONL (one OTLP response per line)
- Time window:      ~10 min lookback (vulture + k6 ran continuously)
- Bundle file size: 30 KB (30 unique traces)

## Ingestion outcome

- Traces ingested:           30
- New observation events:    30
- Idempotent skips:          0
- Adapter warnings:          none

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |     0 |        0%  |
| medium |    29 |       97%  |
| low    |     1 |        3%  |

The single `low` band trace is one of vulture's intentionally
noisy synthetic traces — structurally degenerate but representative
of what vulture is designed to inject.

## Per-rule match counts

| Rule | Matches |
|---|---:|
| All 5 rules | 0 |

Zero rule matches. Honest: Tempo demo has NO realistic application
telemetry. It's:
1. Tempo's own internal traces (control plane: CAS loops, store
   compactions, gRPC frames)
2. Vulture's synthetic random-shape traces (designed to stress
   Tempo, not represent a real application)
3. k6-tracing load-tester output (synthetic load)

None of this is "an application a user is using" — so none of the
rule contracts fire. The engine correctly produced zero clusters.

## Per-abstention counts

| Abstention code | Count |
|---|---:|
| `no_rule_matched` | 30 |

## Cluster counts in digest

- Rule-grounded clusters:      0
- Abstention-grounded clusters: 2
- Total clusters:              2
- Total recurrence:            30

Both clusters are abstention-grounded:
1. `tempo-all` (29 traces) — Tempo's internal control-plane traces
2. `tempo-vulture` (1 trace) — vulture's synthetic random traces

## Defect caught during this run

**Tempo's `/api/traces/<id>` returns OTLP JSON, NOT
Jaeger-compatible JSON.** The earlier (now-deleted) docs claim that
the existing Jaeger adapter "probably works" against Tempo was
false. Net-new adapter
[bin/tempo-export-to-bundles.py](../../../bin/tempo-export-to-bundles.py)
written + 7 unit tests added.

Full narrative + adapter specifics in
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
"Defect 2".

## Telemetry-hygiene findings

Tempo demo is **not a useful target for evaluating ARIP's rule
quality** because its telemetry is structurally synthetic.

What it IS useful for:
- Verifying the Tempo adapter ingests real Tempo wire format
- Confirming the observation pipeline is bounded under synthetic
  random data (2 clusters from 30 random-shape traces is good)
- Validating that low-quality data lands in the `low` band (1 of 30)

What it is NOT useful for:
- Demonstrating any rule cluster firing
- Demonstrating real application failure patterns
- Validating real-world utility of observe-mode

The proper Tempo validation would point a real application that
emits real OTel telemetry to Tempo (instead of Jaeger), then run
this adapter against THAT application's traces. That's a separate,
real-engineer-pilot test.
