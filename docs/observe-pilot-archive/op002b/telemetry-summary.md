# Telemetry summary — `op002b` (OTel Demo + fault injection, no logs)

_Factual data only. Runner-self-pilot continuation of op002. See
`feedback.md` for warm-up disclaimer and
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
for the cross-system narrative._

## Source

- Backend kind:     Jaeger v2 (embedded in OTel Demo)
- Workload:         `open-telemetry/opentelemetry-demo` with feature
                    flags **enabled** via runtime flagd file edit:
                    - `paymentUnreachable` = on
                    - `cartFailure` = on
                    - `productCatalogFailure` = on
                    - `recommendationCacheFailure` = on
                    - `intlShippingSlowdown` = 5sec
- Adapter:          `bin/jaeger-export-to-bundles.py`
- Time window:      ~10 min lookback with fault flags active
- Bundle file:      4.7 MB / 454 unique traces

## Ingestion outcome

- Traces ingested:           454
- ERROR-status spans (raw):   30 across 4 affected traces
- New observation events:    454
- Adapter warnings:          none

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |     0 |        0%  |
| medium |   448 |     98.7%  |
| low    |     6 |      1.3%  |

## Per-rule match counts

| Rule | Matches |
|---|---:|
| All 5 rules | 0 |

**Zero rule clusters fired** despite real ERROR span chains
crossing service boundaries.

## Per-abstention counts

| Code | Count |
|---|---:|
| `no_rule_matched`  | 451 |
| `weak_evidence`    |   3 |

## Cluster counts in digest

- Rule-grounded clusters:      0
- Abstention-grounded clusters: 17
- Total clusters:              17

## Why no rule cluster (key finding)

The `downstream_error` rule **correctly detected the ERROR chain**:

```
frontend.oteldemo.CheckoutService/PlaceOrder (ERROR)
  ↳ checkout.oteldemo.CheckoutService/PlaceOrder (ERROR)
      ↳ checkout.oteldemo.PaymentService/Charge (ERROR)
          status_message: "name resolver error: produced zero addresses"
```

But the engine's trust contract requires `MIN_EVIDENCE_KINDS >= 2`
before promoting a hypothesis to primary. The Jaeger trace export
contains ONLY span-kind evidence (no log entries). The rule emits
only `Evidence(kind="span")` rows → 1 distinct kind → abstention
escalates to `weak_evidence`.

This is the **trust contract working as designed**. The engine
refuses to promote a rule cluster on span evidence alone, even when
the span pattern is unambiguous.

**Continued in op002c** — same trace bundles + real Loki logs joined.

## Headline finding

Trust contract is **enforceable in practice, not just theory**.
Jaeger-only telemetry pipelines (no log backend wired in) will
produce abstention-heavy digests under fault injection — not
because the engine missed the fault, but because the engine
refuses to nominate a primary with only one kind of evidence.

This is the entire reason `bin/loki-export-to-logs.py` exists.
The op002c follow-up demonstrates the contrast.
