# ARIP — Autonomous Reliability Investigation Platform

**Failing Playwright test → evidence-backed root-cause report, in
seconds, deterministically.** No LLM in the analysis path. No
guessing. Open-source, local-first, CI-friendly.

```
            Investigation summary

  Test                                                     Finding                                          Sev   Conf   Repeats
  checkout latency stays within SLA under concurrent load  Database connection pool exhaustion              high  0.93   0
  checkout returns 200 OK (FAILS under inventory_error)    Downstream inventory-service failure             high  0.90   0
  checkout succeeds without exhausting retries             Retry storm: 5 attempts to inventory.reserve_…   high  0.94   0
  order transitions stay non-interleaved across traces     Concurrent modification across checkout.proc…    high  0.92   0
```

Each row links to a full markdown report with cited evidence — read
real samples in [docs/examples/](docs/examples/) or skim a curated
walkthrough below.

---

## In 15 minutes you can…

```bash
git clone <repo-url> arip && cd arip
bin/arip-demo.sh
```

…go from a fresh clone to four investigated failures, eight curated
markdown reports, a rendered GitHub PR comment, and a populated
cross-run memory store. Demo runs end-to-end in ~30 seconds; the
[QUICKSTART](QUICKSTART.md) talks you through the rest.

| You want…                                  | Read                                                       |
|--------------------------------------------|------------------------------------------------------------|
| The fastest possible path to a running demo | [QUICKSTART.md](QUICKSTART.md)                            |
| The whole story (what / why / how)          | [docs/ARIP_DEMO_WALKTHROUGH.md](docs/ARIP_DEMO_WALKTHROUGH.md) |
| A reading script for a video / screencast   | [DEMO_SCRIPT.md](DEMO_SCRIPT.md) + [docs/demo-moments-cheatsheet.md](docs/demo-moments-cheatsheet.md) |
| Run a real pilot                            | [PILOT.md](PILOT.md) (why) + [docs/PILOT_RUNBOOK.md](docs/PILOT_RUNBOOK.md) (how) + [docs/PILOT_METRICS.md](docs/PILOT_METRICS.md) (metrics) |
| Run **observe-mode** against your telemetry | [docs/OBSERVE_MODE.md](docs/OBSERVE_MODE.md) (what) + [docs/INGESTION_GUIDE.md](docs/INGESTION_GUIDE.md) (per-source recipes) + [docs/OBSERVE_PILOT_KIT.md](docs/OBSERVE_PILOT_KIT.md) (first pilot) |
| Why ARIP sometimes says "I don't know"      | [docs/abstention-gallery.md](docs/abstention-gallery.md)  |
| How ARIP behaves on messy telemetry         | [docs/calibration-gallery.md](docs/calibration-gallery.md) |
| Workflow comparison (manual vs ARIP)        | [docs/before-after-investigation.md](docs/before-after-investigation.md) |
| Curated real outputs (no install needed)    | [docs/examples/](docs/examples/)                          |
| Onboard ARIP to telemetry that isn't the demo's | [docs/ONBOARDING.md](docs/ONBOARDING.md) + [configs/](arip-core/configs/) |
| The trust contract (when ARIP abstains)     | [docs/CALIBRATION.md](docs/CALIBRATION.md)                |
| **Where ARIP fits in the observability ecosystem**, and what it deliberately is NOT | [docs/POSITIONING.md](docs/POSITIONING.md) |
| What ARIP intentionally does NOT do         | the "MVP scope" table below + [docs/POSITIONING.md](docs/POSITIONING.md) + [docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md) |
| The phased plan                             | [ROADMAP.md](ROADMAP.md)                                   |

## What ARIP is (and is not) today

| ✅ MVP scope                                                        | 🚫 explicitly NOT in scope                                  |
|---------------------------------------------------------------------|-------------------------------------------------------------|
| Local-first, Docker Compose                                         | Generic APM / observability vendor                          |
| Playwright-focused failure ingestion                                | AI / LLM-driven hypothesis generation                       |
| **Deterministic** rule-based investigation (5 rules)                | Auto-remediation / self-healing                             |
| Post-failure investigation (read-only)                              | Deterministic replay / time-travel debugging                |
| Evidence-grounded, auditable reports                                | Generic distributed-causality engine                        |
| GitHub Actions integration + sticky PR comment                      | Jira / Slack / PagerDuty integration                        |
| Cross-run fingerprinting + flaky classification                     | Broad connector ecosystem (one good Jaeger path is enough)  |

This is on purpose. Re-evaluate triggers and sketches for the items
in the right column are in [docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md).

## Quick start

```bash
# 1. bring up the demo stack (Jaeger + OTel Collector + Postgres +
#    Redis + payment-service + inventory-service)
docker compose up -d --wait

# 2. install Playwright + ARIP core
( cd tests/playwright && npm install )
( cd arip-core && uv sync --extra dev )

# 3. run the narrated demo
bin/arip-demo.sh
```

On a recent laptop the full Playwright + investigation pipeline runs
in **8–16 seconds**. The MVP's success criterion is < 60 s.

## How it works (one picture)

```
Playwright fails  →  FailureEvent  →  CorrelatedTelemetry  →  Hypotheses  →  Markdown / PR comment
   (tests/)        (collector)        (correlator)          (engine)        (reporter + integrations)
                                                                  ↑↓
                                                          MemoryStore (SQLite)
                                                          · fingerprints
                                                          · test-run history
                                                          · flaky verdicts
```

Five small Python packages under [arip-core/arip_core/](arip-core/arip_core/),
mirrored to five distinct jobs:

| Stage         | Package                                             | What it does                                                                 |
|---------------|-----------------------------------------------------|------------------------------------------------------------------------------|
| Collect       | [`collector/`](arip-core/arip_core/collector/)      | Playwright JSON → `FailureEvent` + `TestRun`                                  |
| Correlate     | [`correlator/`](arip-core/arip_core/correlator/)    | Jaeger + Docker logs → cross-trace timeline                                  |
| Investigate   | [`engine/`](arip-core/arip_core/engine/)            | 5 deterministic rules + evidence audit + abstention                          |
| Remember      | [`memory/`](arip-core/arip_core/memory/)            | SQLite-backed fingerprints + flaky classification                            |
| Report        | [`reporter/`](arip-core/arip_core/reporter/)        | Markdown + optional LLM TL;DR (deterministic fallback)                       |
| Integrate     | [`integrations/`](arip-core/arip_core/integrations/)| GitHub sticky PR comment (under 64 KB budget)                                |

Architectural detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Rule design in [docs/INVESTIGATION_RULES.md](docs/INVESTIGATION_RULES.md).

## What makes this credible

- **Evidence integrity audit.** Every cited span_id / trace_id /
  log line must exist in the telemetry. Ungrounded evidence is dropped
  and confidence is decayed. (`engine/evidence_audit.py`)
- **Abstention by design.** Engine declines to nominate a primary
  hypothesis in four well-defined cases (no primary trace, empty
  telemetry, no rule matched, weak evidence). Sample output in
  [docs/examples/abstention.md](docs/examples/abstention.md).
- **Cross-run fingerprinting.** Rule + service set + evidence shape →
  stable 16-char hash, independent of trace IDs and timestamps.
  Worked example: [docs/examples/fingerprint-cross-run.md](docs/examples/fingerprint-cross-run.md).
- **Tail-based sampling that never loses an interesting trace.**
  Always-keep policies for ERROR, slow, and `arip.force_sample=true`.
  See [demo-env/otel-collector/config.yaml](demo-env/otel-collector/config.yaml).
- **62 unit tests.** Engine rules and integrations are tested with
  synthetic telemetry, no live stack required.

## Rule registry (5 deterministic rules)

| rule_id                    | Detects                                                | Abstains when…                                              |
|----------------------------|--------------------------------------------------------|-------------------------------------------------------------|
| `concurrent_modification`  | Two operations mutating the same `order.id` in overlapping time | Single trace, or no time overlap, or only one side wrote   |
| `retry_storm`              | Same operation retried 2+ times with `retry.*` metadata | `retry.attempt` attribute missing; only one attempt visible |
| `downstream_error`         | ERROR chain bottoming out in a different service        | No cross-service ERROR pair                                 |
| `db_pool_exhaustion`       | `db.pool.*` saturation on an acquire span               | Pool attributes missing — does NOT speculate                |
| `latency_vs_db`            | Application latency above the DB layer (≥ 10× ratio)    | Handler too fast, or no DB child, or below ratio            |

Full rule registry (confidence signals, source pointers) in
[docs/INVESTIGATION_RULES.md](docs/INVESTIGATION_RULES.md).
The 5 failure patterns the demo stack injects, mapped per rule with
trigger / signature / evidence / abstention condition, is in
[docs/FAILURE_MATRIX.md](docs/FAILURE_MATRIX.md).

## Failure scenarios shipped

Five deterministic, telemetry-clean failure injections. The
applications never advertise which scenario is running — the engine
reads only what production instrumentation would emit anyway:

| Scenario             | Trigger header                | What the trace looks like                                |
|----------------------|-------------------------------|----------------------------------------------------------|
| `slow_query`         | `X-Failure-Mode: slow_query`   | Handler ≫ DB time (10× ratio); no pool, no retries       |
| `inventory_error`    | `X-Failure-Mode: inventory_error` | Single ERROR chain across two services                |
| `webhook_race`       | parallel `/checkout`+`/webhook` | Two traces, same `order.id`, overlap in time            |
| `pool_exhaustion`    | `X-Failure-Mode: pool_exhaustion` + concurrent | `db.acquire_connection` slow; `db.pool.*` saturated |
| `retry_storm`        | `X-Failure-Mode: retry_storm`  | 5× `inventory.reserve_attempt`; exponential backoff      |

Full telemetry signatures in [docs/FAILURE_SCENARIOS.md](docs/FAILURE_SCENARIOS.md).
Per-rule abstention contracts in [docs/FAILURE_MATRIX.md](docs/FAILURE_MATRIX.md).

## GitHub Actions

The workflow in [.github/workflows/arip-investigate.yml](.github/workflows/arip-investigate.yml)
runs on push and pull_request, brings up the demo stack on the runner,
executes Playwright, investigates each failure, and posts a sticky
PR comment with header `arip-investigation`. Repeat runs update the
same comment in place (de-duped via the header). Reports are uploaded
as a workflow artifact (`arip-reports`) with 14-day retention.

A pre-rendered example of what the comment looks like is in
[docs/examples/pr-comment.md](docs/examples/pr-comment.md).

## Running pieces individually

```bash
# investigate a Playwright report
cd arip-core
uv run arip investigate ../tests/playwright/playwright-report.json --out ../reports

# render a PR-style comment from those reports
uv run arip pr-comment ../reports --out ../arip-pr-comment.md
```

Set `ANTHROPIC_API_KEY` to enable the LLM TL;DR; without it the
report is fully deterministic.

## Repository layout

```
arip/
├── README.md               you are here
├── ROADMAP.md              phased roadmap (Phase 1 ✓ shipped)
├── docs/
│   ├── ARIP_DEMO_WALKTHROUGH.md   read this first
│   ├── ARCHITECTURE.md            module boundaries + what's not built
│   ├── INVESTIGATION_RULES.md     current rules + how to add one
│   ├── FAILURE_SCENARIOS.md       per-scenario telemetry signatures
│   ├── FUTURE_ARCHITECTURE.md     deferred items + triggers
│   └── examples/                  real curated outputs (PR comment, RCAs, …)
├── arip-core/              Python: collector / correlator / engine / memory / reporter
├── demo-env/               Go services + OTel Collector + Postgres + failure-injector scripts
├── tests/playwright/       Playwright integration tests (one per failure pattern)
├── bin/
│   ├── arip-demo.sh                   narrated 6-step golden demo
│   ├── arip-e2e.sh                    unattended CI-style run
│   ├── jaeger-export-to-bundles.py    operator-side adapter (Jaeger HTTP API)
│   ├── tempo-export-to-bundles.py     operator-side adapter (Tempo OTLP JSON)
│   ├── loki-export-to-logs.py         operator-side adapter (Loki streams)
│   ├── observe-self-audit.sh          30-sec pre-pilot smoke check
│   └── run-observe-pilot.sh           single-command observe-mode pilot runner
└── .github/workflows/      GitHub Actions: investigate + sticky PR comment
```

## Status

**Phase 1 (MVP) — shipped, validated locally, in shipping mode.**
The five rules, the deterministic engine, the cross-run memory, the
GitHub Actions integration, and the documentation set are all in
their v0.1.0 shape. Phase 2/3/4 plans are in [ROADMAP.md](ROADMAP.md);
they will move only when there is a concrete user reason.

Pre-release validation:

- **169/169 unit tests pass** (`cd arip-core && uv run pytest`) — includes
  10 calibration-benchmark scenarios, 16 observation stress scenarios,
  9 real-world ingestion validation tests, 7 Tempo adapter tests, and
  16 Cypress listener tests
- **Investigation mode supports Playwright AND Cypress** — `arip
  investigate <report.json>` auto-detects the framework
- **GitHub Actions template for observe-mode** —
  [`.github/workflows/arip-observe.yml.example`](.github/workflows/arip-observe.yml.example)
  for scheduled weekly anomaly digests
- **End-to-end demo** completes in ≤ 16 seconds (success criterion: < 60 s)
- **4 distinct rule fingerprints** produced reproducibly across runs
- **Observe-mode** (Phase A) shipped read-only; see
  [docs/PHASE_A_VALIDATION.md](docs/PHASE_A_VALIDATION.md) for the
  stress + real-world ingestion validation passes
- **Five unknown-OSS-system validations completed** — Jaeger HotROD
  (op001), CNCF OpenTelemetry Demo (op002 healthy / op002b faulted /
  op002c faulted+Loki), Grafana Tempo (op003). Two real defects
  caught + fixed during validation. **op002c milestone: first rule
  cluster (`downstream_error`, high quality) on telemetry the engine
  had never seen, with real Loki logs joined through the adapter
  chain.** See
  [docs/UNKNOWN_SYSTEMS_VALIDATION.md](docs/UNKNOWN_SYSTEMS_VALIDATION.md)

Per-release runbook: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

License: Apache-2.0 — see [LICENSE](LICENSE).
