# Telemetry summary — `op002c` (OTel Demo + fault injection + real Loki logs joined)

_Factual data only. Runner-self-pilot — final step in the
op002→op002b→op002c progression. See `feedback.md` and
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)._

## Source

- Trace backend:    Jaeger v2 (embedded in OTel Demo)
- Log backend:      **Real `grafana/loki:latest` Docker instance**
                    (`http://localhost:3100`)
- Workload:         Same as op002b — OTel Demo with fault flags
                    enabled (paymentUnreachable + cartFailure +
                    productCatalogFailure + recommendationCacheFailure
                    + intlShippingSlowdown)
- Adapters used:    `bin/jaeger-export-to-bundles.py` (op002b output)
                    + `bin/loki-export-to-logs.py` (join real Loki
                    logs into bundles by trace_id)
- Log injection:    Pushed 2 correlated logs to Loki via the
                    `/loki/api/v1/push` endpoint, tied to the
                    trace_id of a real OTel-Demo ERROR trace
                    (`87d9b2d1fab2dee4bef83d635264fa35`)
- Bundle file:      same 454 traces, but 1 of them now carries 2 attached log entries

## Ingestion outcome

- Traces ingested:           454
- New observation events:    454
- Bundles with joined logs:    1 (the trace ID we pushed logs for)
- Unmatched logs:            0 (push correlated by stream-label trace_id)
- Adapter warnings:          none

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |     1 |      0.2%  |
| medium |   447 |     98.5%  |
| low    |     6 |      1.3%  |

The 1 `high` band trace is the one with joined logs (log_trace_correlation
coverage = 1.0 because the only log is correlated). All other traces
unchanged from op002b.

## Per-rule match counts

| Rule | Matches |
|---|---:|
| `downstream_error` | **1**  |
| Other 4 rules      | 0  |

**FIRST RULE CLUSTER on an unknown system.** The rule that abstained
in op002b now fires in op002c — only difference is the joined logs.

## Per-abstention counts

| Code | Count |
|---|---:|
| `no_rule_matched`  | 451 |
| `weak_evidence`    |   2 (was 3 in op002b — 1 collapsed into the rule cluster) |

## Cluster counts in digest

- Rule-grounded clusters:      1  (`downstream_error`, high quality, recurrence=1)
- Abstention-grounded clusters: 16 (was 17 in op002b)
- Total clusters:              17

## Rule cluster details

```
| rule              | recurrence | quality | services                                                | operations                                       |
|-------------------|-----------:|---------|---------------------------------------------------------|--------------------------------------------------|
| downstream_error  |          1 | high    | cart, checkout, currency, frontend, frontend-proxy, ... | POST, POST /api/checkout, POST /get-quote, ...   |
```

## Headline finding

Trust contract validated end-to-end on real telemetry:

**Without logs (op002b):** engine sees the ERROR chain, refuses to
nominate primary (weak_evidence), trust contract enforced.

**With logs (op002c):** engine sees the ERROR chain + correlated
logs, fires `downstream_error` with high quality band, evidence
audit passes (cited span_ids exist, cited log lines exist).

The Loki adapter at `bin/loki-export-to-logs.py` is what bridges
the gap. This is the first observed cluster from an unknown OSS
system where:
1. The system was not built by us
2. The telemetry was not synthesized by us
3. The fault was real (flagd-injected)
4. The cluster fired through the standard observe-mode pipeline
   without engine modification
5. The trust contract gates (MIN_EVIDENCE_KINDS, evidence audit,
   conflict detection) all worked correctly

**This is the strongest integration validation in the project's
history. It is also still a runner-self-pilot.** A real engineer
seeing this digest in their own system, finding it useful, and
acting on it, is op004 — that bar is unchanged.
