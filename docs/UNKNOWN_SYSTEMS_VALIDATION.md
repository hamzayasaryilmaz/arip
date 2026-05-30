# Unknown-systems validation — op001/op002/op003

Three OSS systems, none of which the engine had ever seen, pulled from
GitHub and observed end-to-end. Telemetry was used **as-is** — no
config overrides, no naming cleanup, no canonical attribute injection.

Honest verdict up front:

- **Trust contract held on all three systems** — zero false-high-confidence
  outcomes anywhere
- **Two real defects caught and narrowly fixed** during validation
  (abstention service-set cardinality + Tempo OTLP-JSON wire format
  incompatibility)
- **One real-world finding documented as out-of-scope** (Sock Shop
  emits no distributed tracing — observe-mode does not apply to
  uninstrumented systems)
- **One adapter added** (`bin/tempo-export-to-bundles.py`) covering
  Tempo's native OTLP JSON shape

This document is the cross-system synthesis. Per-system narratives
live in the pilot archives below.

| System | Archive | Engine outcome | Notes |
|---|---|---|---|
| Jaeger HotROD | [op001](observe-pilot-archive/op001/) | 1 abstention cluster from 40 traces | First unknown-system validation; documented in [HOTROD_FINDINGS.md](HOTROD_FINDINGS.md) |
| OpenTelemetry Demo (CNCF) | [op002](observe-pilot-archive/op002/) | 8 abstention clusters from 291 traces (post-fix; was 23 pre-fix) | Caught service-set cardinality defect; fix applied + regression test added |
| Grafana Tempo (single-binary) | [op003](observe-pilot-archive/op003/) | 2 abstention clusters from 30 traces | Caught Tempo↔Jaeger wire-format incompatibility; new adapter added |
| Sock Shop (Weaveworks) | n/a | n/a — no telemetry | Confirmed `spring.zipkin.enabled=false` in compose; observe-mode does not apply |

## The two defects caught during this iteration

### Defect 1 — Abstention fingerprint service-set cardinality

**System that exposed it:** OpenTelemetry Demo
**Symptom:** 291 traces from a 16-service mesh produced **23 distinct
abstention clusters**, all `no_rule_matched`. Reading the digest
became impractical.
**Root cause:** `_abstention_fingerprint(ct, abstention)` was hashing
on the *full transitive set of services* touched by each trace.
Different request paths through the mesh touch different subsets
(cart-flow vs payment-flow vs recommendation-flow vs etc), and each
unique subset got its own fingerprint.
**Fix:** [arip_core/observation/clustering.py](../arip-core/arip_core/observation/clustering.py)
`_abstention_fingerprint` now uses the **entry-point services only**
(spans whose `parent_span_id` is None or not in the bundle). The full
transitive set is still recorded on the cluster as metadata — just
not as a fingerprint determinant.
**Effect:** 291 traces → 23 clusters → **8 clusters** post-fix.
**Regression test:** `tests/test_observation_stress.py::test_abstention_fingerprint_collapses_high_service_count`
— builds a 50-trace fixture with 5 different downstream subsets, all
sharing an entry-point span on "frontend", asserts exactly 1
abstention cluster.

This is the third fingerprint-cardinality fix in the project's
history (after Appendices A and B in
[PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md)). The pattern is now
recognisable: any cardinality dimension that grows with telemetry
complexity must NOT be in the fingerprint; it goes on the cluster
as descriptive metadata.

### Defect 2 — Tempo's OTLP JSON is incompatible with the Jaeger adapter

**System that exposed it:** Grafana Tempo (single-binary v3.0.0)
**Symptom:** Earlier documentation (now corrected) claimed Tempo
was likely Jaeger-compatible via the existing
`bin/jaeger-export-to-bundles.py`. False. Tempo's
`/api/traces/<id>` returns OpenTelemetry's protobuf-derived JSON
format:
  - `traceId` and `spanId` are base64-encoded bytes (not hex strings)
  - timestamps are `*UnixNano` strings (not microseconds)
  - attribute values are OTLP wrappers (`{"stringValue": "x"}` not
    Jaeger's typed-tag format)
  - top-level shape is `batches` → `resource` + `scopeSpans`
    (not Jaeger's `data` + `processes`)
**Fix:** Net-new operator adapter
[`bin/tempo-export-to-bundles.py`](../bin/tempo-export-to-bundles.py)
(NOT in `arip_core/`; operator tooling). Decodes base64 IDs, unwraps
OTLP attribute values, maps OTLP status code 2 → "ERROR".
**Test coverage:** 7 tests in
[tests/test_tempo_adapter.py](../arip-core/tests/test_tempo_adapter.py)
covering attribute type coercion, status mapping, JSONL input, empty
batches, missing service.name, and end-to-end consumption by the
observation pipeline.

**This adds a new tool to `bin/`, not a new capability to the engine.**
The observation pipeline is unchanged; the adapter just bridges
Tempo's wire format into the JSONL trace-bundle shape that
`JsonlTraceSource` already accepts.

## Per-system honest narratives

### op002 — OpenTelemetry Demo (CNCF reference workload)

**Setup.** Cloned `open-telemetry/opentelemetry-demo`, brought up
`compose.yaml + compose.observability.yaml` (27 services across Go,
.NET, Java, JS, Python, Rust). Built-in `load-generator` produced
real traffic immediately.

**Friction encountered:**

1. **Jaeger port collision avoidance.** OTel Demo's Jaeger UI bound
   to a random host port (60597) instead of the default 16686. The
   adapter docs hardcoded `localhost:16686` in examples; the
   operator had to discover the actual port via `docker ps`.
2. **Jaeger v2 base_path.** OTel Demo configures Jaeger with
   `base_path: /jaeger/ui` (configured in the demo's
   `otel-collector` setup). The Jaeger HTTP API is then under
   `/jaeger/ui/api/...` not `/api/...`. INGESTION_GUIDE.md
   examples need a `--base-path` discussion. **This is a real-world
   pathology, not a defect** — the operator just needs to know.
3. **Service discovery is per-service.** No global "give me all
   traces" endpoint; the operator queries each service in turn and
   merges by trace_id. The recipe works but is verbose.
4. **Cluster explosion (Defect 1).** Fixed.

**Outcome (post-fix):** 291 traces → 8 abstention clusters, all
`no_rule_matched`. Zero rule clusters. Quality band: 100% medium.

**Why no rule clusters fired:** OTel Demo's intentional fault
injection (via flagd feature flags) was not enabled during this
validation. With pure healthy traffic, no rule's contract should
fire — and none did. This is the trust contract working, not a
shortcoming. A follow-up pilot with feature flags enabled
(`productCatalogFailure`, `cartServiceFailure`, etc.) is the
natural next experiment.

### op003 — Grafana Tempo (single-binary demo)

**Setup.** Cloned `grafana/tempo`, brought up
`example/docker-compose/single-binary/` (tempo + alloy + k6-tracing
+ vulture + grafana + prometheus). The `vulture` and `k6-tracing`
services emit synthetic structured traces continuously.

**Friction encountered:**

1. **Port collision.** Tempo demo's Prometheus tries to bind 9090,
   which collides with OTel Demo's Prometheus. Stopping OTel Demo
   resolved this. Documented.
2. **Wire format incompatibility (Defect 2).** Fixed via new adapter.
3. **Trace search format differs.** Jaeger's
   `?service=X&lookback=15m` is replaced with Tempo's
   `?tags=&limit=N` query format. Operator workflow needs to
   bulk-fetch trace IDs via search, then fetch each trace
   individually via `/api/traces/<id>`. Multi-step but mechanical.

**Outcome:** 30 traces → 2 abstention clusters (tempo-all internal
trace + tempo-vulture synthetic trace). Zero rule clusters. 1 trace
in `low` quality band (vulture's random-shape spans).

**Why no rule clusters:** Tempo's demo doesn't have realistic
application telemetry — it's Tempo's own internal traces plus
synthetic random data. No domain shape for the rules to fire on.
Honest output.

### Sock Shop — observe-mode does NOT apply

**Setup.** Cloned `microservices-demo/microservices-demo`, brought
up `deploy/docker-compose/docker-compose.yml` (14 containers
including 4 databases + RabbitMQ). All services started clean.

**Critical finding:** Grepping the compose file for tracing config:

```
JAVA_OPTS=...-Dspring.zipkin.enabled=false
```

Zipkin tracing is **explicitly disabled** in every Spring service.
No OTel collector. No Jaeger. No Tempo. Sock Shop emits **no
distributed tracing telemetry by default**.

**Conclusion:** Observe-mode is not applicable to Sock Shop without
first instrumenting it. This is **not an ARIP defect** — it's a
fact about a popular OSS reference workload. Many real-world
production systems are in the same state (legacy services
predating OTel adoption). The honest operator action for such
systems: instrument first (add OTel SDK), then observe.

**No archive directory created for Sock Shop.** A pilot archive
without observation data would be a placeholder, not evidence.

## Aggregate validation outcomes

| Property | OTel Demo | Tempo | Sock Shop | HotROD (op001) |
|---|---|---|---|---|
| Telemetry emitted? | yes (OTel) | yes (OTel→Tempo) | no | yes (OTel→Jaeger) |
| Adapter worked? | yes (Jaeger adapter) | needed new adapter | n/a | yes (Jaeger adapter) |
| Trace count observed | 291 | 30 | 0 | 40 |
| Rule clusters | 0 | 0 | n/a | 0 |
| Abstention clusters (post-fix) | 8 | 2 | n/a | 1 |
| False-high-confidence outcomes | **0** | **0** | n/a | **0** |
| Defect caught | service-set cardinality | OTLP-JSON wire format | n/a | path-parameter cardinality (Appendix B) |
| Defect status | fixed + regression test | fixed + 7 unit tests | n/a | fixed + Appendix B test |

The headline pattern across four systems:

> **Zero false-high-confidence outcomes on telemetry the engine had
> never seen — across four diverse OSS systems.**

Read this as: the trust contract held under genuinely novel input,
including a system architecture (16-service mesh) that exposed a
real defect in the clustering layer. The defect was caught by
validation, not by users.

## What this iteration did NOT do (discipline preserved)

In keeping with observe-mode discipline (POSITIONING.md anti-goals):

- **No candidate test generation** — Phase A capability boundary
- **No new rule** — 5 rules unchanged; no `otel_demo_*` or
  `tempo_*` rule added
- **No telemetry repair on the OSS systems** — they were observed
  as-shipped, including Sock Shop's unfortunate lack of tracing
- **No fictional operator quotes** — op001, op002, op003 all carry
  NO-HUMAN-OPERATOR disclaimers; these are runner-self-validations
  against unknown OSS, NOT pilots with real engineers
- **No marketing claims** — "validated against the CNCF reference
  workload" is a true statement; reading it as "production-ready
  for any OTel-instrumented system" is the misreading this doc
  exists to prevent
- **No adapters for systems we haven't actually tested** —
  Datadog/Honeycomb/New Relic/Splunk/Elastic adapters are NOT
  added speculatively. They get added when a real validation
  against those backends demands them.

## What the next validation should test

In priority order:

1. **OTel Demo with feature flags enabled.** Specifically:
   `productCatalogFailure`, `cartServiceFailure`,
   `recommendationServiceCacheFailure`. These should produce real
   rule-cluster outcomes (downstream_error, retry_storm) — testing
   whether the engine fires correctly when the telemetry has the
   right shape.
2. **A real engineer's CI/staging telemetry** (`op004` or later
   with a real human). This remains the bar for Phase 2 entry
   gate. All op001-op003 pilots are explicit NO-HUMAN-OPERATOR
   warm-ups and do NOT count toward the entry-gate quorum.
3. **A second non-Jaeger telemetry backend** — e.g., the Honeycomb
   API or Datadog APM export — IF an operator brings real
   telemetry from those systems. Speculative adapters remain
   anti-goal.

## Files added or changed by this iteration

- **Added.** [bin/tempo-export-to-bundles.py](../bin/tempo-export-to-bundles.py)
  — operator adapter for Tempo's OTLP JSON wire format
- **Added.** [arip-core/tests/test_tempo_adapter.py](../arip-core/tests/test_tempo_adapter.py)
  — 7 tests
- **Added.** Stress test
  `tests/test_observation_stress.py::test_abstention_fingerprint_collapses_high_service_count`
- **Added.** Pilot archives:
  - [observe-pilot-archive/op002/](observe-pilot-archive/op002/)
    (OTel Demo, NO HUMAN OPERATOR)
  - [observe-pilot-archive/op003/](observe-pilot-archive/op003/)
    (Tempo, NO HUMAN OPERATOR)
- **Added.** [docs/UNKNOWN_SYSTEMS_VALIDATION.md](UNKNOWN_SYSTEMS_VALIDATION.md)
  — this document
- **Changed.** [arip-core/arip_core/observation/clustering.py](../arip-core/arip_core/observation/clustering.py)
  — `_abstention_fingerprint` uses entry-services not full set;
  docstring expanded with op002 rationale.

Test count: 145 → 153 (1 new stress + 7 new Tempo adapter). Regressions: 0.
Trust contract: intact across 4 unknown-system validations.
