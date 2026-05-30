# OSS pilot candidates for observe-mode

A working shortlist of public OSS systems that could serve as the
first real-world telemetry sources for an observe-mode pilot. These
are not a substitute for an actual production engineer's CI/staging
telemetry — they're a meaningful step up from this repo's local
`demo-env/`, with externally-maintained OTel instrumentation, public
fault-injection controls, and richer cross-service traces.

Honest framing: a pilot against any of these is "first-step real"
(externally-built reference workload), not "production real" (the
engineer's own system under real load). Both are pilots. Both
produce useful signal. Treat OSS-candidate pilots as the warm-up;
treat real engineer pilots as the bar.

## Evaluation criteria

For each candidate, the rubric is:

| Criterion | Why |
|---|---|
| Existing OTel instrumentation | No instrumentation work as part of the pilot |
| Public ability to export traces (Jaeger / Tempo / OTLP) | Adapter recipe known |
| Built-in or easy fault injection | Otherwise nothing recurs, abstention-heavy digest |
| Cross-service spans (multi-service traces) | Single-service traces collapse to thin shapes |
| Lightweight to run locally (≤ Docker Compose) | 30-minute pilot budget |
| Active maintenance | Won't bit-rot before the pilot |
| Permissive licence | Pilot artefacts can be committed publicly |

## Shortlist

### A. OpenTelemetry Demo (CNCF reference workload)

- **Repo:** `open-telemetry/opentelemetry-demo`
- **What it is:** the CNCF reference microservices workload — a
  full e-commerce app (12+ services in Go, .NET, Java, JS, Python,
  Rust, etc.) instrumented end-to-end with OTel. Ships with
  Jaeger, Prometheus, Grafana, OpenSearch.
- **Why it fits:** the project's design intent is *exactly* to be a
  realistic OTel-emitting workload. Feature flags (via `flagd`) in
  the deployment let operators toggle fault scenarios:
  `productCatalogFailure`, `recommendationServiceCacheFailure`,
  `cartServiceFailure`, `paymentServiceFailure`, etc. These
  *produce* recurring anomaly patterns observe-mode can cluster.
- **Pilot fit:** ⭐⭐⭐⭐⭐. The closest thing to "real production
  telemetry on tap" in the OSS world.
- **Setup cost:** ≤ 10 min (`docker compose up`). Jaeger UI on
  `localhost:16686`.
- **Adapter to use:** `bin/jaeger-export-to-bundles.py` against
  Jaeger's `/api/traces` endpoint with a service/lookback filter.
- **Pilot recipe (sketch):**
  1. `git clone open-telemetry/opentelemetry-demo && docker compose up -d`
  2. Wait ~2 min for services to settle
  3. Enable `productCatalogFailure` flag for ~5 minutes via the
     load-generator UI
  4. Export traces:
     `curl 'http://localhost:16686/api/traces?service=productcatalogservice&lookback=15m&limit=500' > /tmp/otel-demo.json`
  5. Convert:
     `python3 bin/jaeger-export-to-bundles.py --in /tmp/otel-demo.json --out /tmp/otel-demo.jsonl`
  6. Pilot:
     `./bin/run-observe-pilot.sh /tmp/otel-demo.jsonl op001`
- **Caveat:** the demo's "anomalies" are intentionally clean. A
  pilot here validates that observe-mode produces a readable
  digest under realistic-but-controlled telemetry, not that it
  handles real production messiness. For the latter, see candidate D.

### B. Jaeger HotROD

- **Repo:** `jaegertracing/jaeger` (examples/hotrod)
- **What it is:** Jaeger's own canonical demo — a 4-service Go app
  (frontend, customer, driver, route) emitting OTel traces. The
  original "look at trace examples" reference.
- **Why it fits:** small, well-understood telemetry shape. Native
  Jaeger emission. Predictable cross-service spans. Lower setup
  than the full OTel demo if you want a faster pilot.
- **Pilot fit:** ⭐⭐⭐⭐. Smaller than candidate A; correspondingly
  fewer anomaly shapes to observe.
- **Setup cost:** ≤ 5 min (single Docker container).
- **Adapter:** same as candidate A.
- **Caveat:** HotROD's "anomalies" are coarser — high latency, lock
  contention. Observe-mode will likely see one or two rule clusters
  (`latency_vs_db`) and a lot of `no_rule_matched` abstentions.
  That's an honest pilot outcome but doesn't exercise the engine's
  full repertoire.

### C. Google Online Boutique (microservices-demo)

- **Repo:** `GoogleCloudPlatform/microservices-demo`
- **What it is:** Google's reference cloud-native demo — 11
  microservices in 7 languages, cart/payment/email flow.
  OTel instrumentation is opt-in via a side configuration.
- **Why it fits:** comparable scope to candidate A, different
  architecture intent (more "real-world product shape", less
  "telemetry-first design").
- **Pilot fit:** ⭐⭐⭐. Setup cost is higher (Kubernetes is the
  primary deploy target; Docker Compose is a workaround). OTel
  isn't on by default.
- **Recommendation:** skip in favour of candidate A unless the
  pilot's operator has GKE / minikube already running.

### D. Engineer's own CI / staging telemetry

- **What it is:** the actual goal.
- **Why it fits:** validates trust contract against real-world
  messiness — partial propagation, naming inconsistency, sampled
  traces, logs without trace_id. The validation suite in
  [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) covers each of
  these shapes synthetically, but real telemetry combines them in
  ways no fixture can.
- **Pilot fit:** ⭐⭐⭐⭐⭐. The bar.
- **Setup cost:** variable — depends entirely on whether the
  engineer can export 1 hour of telemetry. If yes, ≤ 10 min. If no,
  the pilot is blocked on telemetry export plumbing the engineer
  has to do anyway.
- **Adapter:** depends on backend:
  - Jaeger → `bin/jaeger-export-to-bundles.py`
  - Loki → `bin/loki-export-to-logs.py` (join phase)
  - Tempo → Tempo's JSON output is Jaeger-compatible; use the
    Jaeger adapter
  - GHA artifacts → unzip + `arip observe` against the directory
  - S3 archives → see [INGESTION_GUIDE.md](INGESTION_GUIDE.md)
- **Caveat:** the engineer's telemetry may be too thin to produce a
  useful digest at all. The self-audit step (`bin/observe-self-audit.sh`)
  catches this in 30 seconds before the pilot starts.

## Recommended pilot ordering

**Updated after iteration:** the original op001-op003 plan was for
op001 as a single warm-up, op002 as the first real engineer. The
actual sequence ran differently — three runner-self-pilots against
three different unknown OSS systems (HotROD, OTel Demo, Tempo) so
the validation surface area is wider before recruiting a real
engineer. See [UNKNOWN_SYSTEMS_VALIDATION.md](UNKNOWN_SYSTEMS_VALIDATION.md).

The recommended ordering NOW is:

1. ✓ **op001 (DONE)**: Jaeger HotROD — smallest, fastest unknown-system
   smoke test. Established the pattern of writing pilot archives
   with NO-HUMAN-OPERATOR disclaimers for runner-self-pilots.
2. ✓ **op002 (DONE)**: OpenTelemetry Demo (CNCF reference workload) —
   exposed the abstention service-set cardinality defect; fix +
   regression test applied.
3. ✓ **op003 (DONE)**: Grafana Tempo — exposed the Tempo↔Jaeger
   wire-format incompatibility; new adapter + 7 unit tests added.
4. ☐ **op004 (NEXT — first REAL engineer):** the engineer recruited
   via [observe-pilot-recruitment.md](observe-pilot-recruitment.md),
   running against their own CI/staging telemetry (candidate D).
   **This is the bar for Phase 2 entry gate.**
5. ☐ **op005, op006:** more engineers; synthesise after op006 per
   [PILOT_SYNTHESIS_TEMPLATE.md](PILOT_SYNTHESIS_TEMPLATE.md).

The warm-up pilot is explicitly labelled as such — its
`feedback.md` records "no real operator; runner-self-pilot to
validate machinery only; do NOT count toward Phase 2 entry gate".
That's the honest discipline.

## What this list deliberately excludes

- **Hosted SaaS demos** (Honeycomb sandbox, Lightstep sandbox, etc.)
  — can't export raw traces without an account commitment, and the
  privacy contract is weaker
- **Anonymised dataset dumps** (academic OTel datasets) — frozen,
  no fault injection, no recurrence to detect, abstention-heavy
- **Proprietary observability vendor reference workloads** — same
  hosted-SaaS issue

If a candidate exists in this space that genuinely meets all the
criteria above, add it here with a short evaluation. Don't add
candidates speculatively — every one on the shortlist has been
checked against the rubric.

## Cross-references

- [OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md) — the pilot kit
- [observe-pilot-recruitment.md](observe-pilot-recruitment.md) —
  the package to send to candidate engineers
- [OBSERVE_OPERATOR_BRIEFING.md](OBSERVE_OPERATOR_BRIEFING.md) —
  the 5-min note the operator reads before the session
- [INGESTION_GUIDE.md](INGESTION_GUIDE.md) — per-source adapter
  recipes
- [observe-digest-examples.md](observe-digest-examples.md) —
  what to expect the digest to look like
