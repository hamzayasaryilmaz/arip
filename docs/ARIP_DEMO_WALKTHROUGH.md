# ARIP — Demo Walkthrough

> Read this first.
>
> By the end of this page (≈15 minutes) you will have:
> 1. brought up the demo stack,
> 2. watched a Playwright test fail in five different failure modes,
> 3. read the evidence-backed root-cause report ARIP produced for each,
> 4. seen what makes the engine refuse to guess.

---

## What ARIP is (in 90 seconds)

ARIP — Autonomous Reliability Investigation Platform — turns a failing
end-to-end test into a markdown report that names the root cause and
points at the exact telemetry that proves it.

A failure investigation that used to take an engineer 30–120 minutes
of manual log/trace digging happens automatically, in seconds,
**from the same telemetry already collected.**

ARIP is **not** a general-purpose APM, not a chatbot, not an
auto-remediator. It does one narrow thing well: **post-mortem of a
single failing test, in a CI-friendly format.**

---

## The problem this exists for

Modern distributed systems fail in ways that resist single-screen
debugging:

- the failing test prints "`expected 200, got 502`"
- the cause is 4 services and 1.5 seconds away
- the trace ID is buried in one of dozens of log lines
- the actual signal lives in a span attribute most engineers never
  look at (`db.pool.wait_ms`, `retry.attempt`, …)
- by the time someone has the context, an hour is gone

Today an engineer does this manually. ARIP does it deterministically.

---

## Architecture in one picture

```
Playwright fail  →  FailureEvent  →  CorrelatedTelemetry  →  Hypotheses  →  Report
                                  ↑                        ↑
                       Jaeger (traces)              5 deterministic rules
                       Docker logs                    + evidence audit
                                  ↓                  + abstention
                       MemoryStore (SQLite)
                       · fingerprints
                       · per-test history
                       · flaky verdicts
                                  ↓
                       PR comment / artifact
```

Five small Python packages do five distinct jobs.
[ARCHITECTURE.md](ARCHITECTURE.md) has the longer story.

---

## Prerequisites

| Tool         | Minimum version | Why                                                                        |
|--------------|-----------------|----------------------------------------------------------------------------|
| Docker + Compose v2 | recent | Demo stack — Jaeger, OTel Collector, Postgres, Redis, payment, inventory   |
| Node         | 20.x            | Playwright test runner                                                     |
| `uv`         | 0.5+            | Python dep & venv manager — installs Python 3.12 if not present            |
| `curl`       | any             | Used by the runners + demo scripts for health checks                        |
| `python3`    | any (≥ 3.8)     | Runs the small JSON-walking helpers inside the demo scripts                 |

Install `uv` (one-liner, no Python needed first):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## One-command demo

```bash
git clone <repo> && cd arip
bin/arip-demo.sh
```

That's it. The runner does its own preflight + self-bootstrap:

- Verifies `docker`, `node ≥ 20`, `npm`, `uv`, `curl`, `python3` are on PATH.
- Runs `npm install` in `tests/playwright/` if `node_modules/` is missing.
- Runs `uv sync --extra dev` in `arip-core/` if `.venv/` is missing.
- Brings up the Docker Compose stack.
- Resets the inventory table so the demo is reproducible run-to-run.
- Walks the six-stop golden path (A → F) with narration.

If any prerequisite is missing the runner errors with a one-line
diagnostic and points at the install instructions above.

Two related entry points:

- **`bin/arip-demo.sh`** — narrated, step-by-step. Use this when
  showing the project to a person.
- **`bin/arip-e2e.sh`** — unattended CI-style run. Same pipeline,
  no narration. Use this when scripting against ARIP.

On a recent laptop the demo runs end-to-end in ~30 s including both
the first and second (cross-run) passes.

## Expected output

After `bin/arip-demo.sh` finishes you will have:

```
arip/
├── reports/                            8 markdown + 8 JSON
│   ├── checkout-latency-stays-within-sla-…md
│   ├── checkout-returns-200-ok-fails-under-inventory-error-…md
│   ├── checkout-succeeds-without-exhausting-retries-…md
│   └── order-transitions-stay-non-interleaved-across-traces-…md
├── arip-pr-comment.md                  one consolidated PR-comment view
└── .arip/memory.db                     SQLite memory (4 fingerprints, 10 test runs)
```

Five rules. Four distinct primary hypotheses. Each report cites real
spans + real logs. The PR comment is what GitHub Actions posts as a
sticky comment.

## Troubleshooting

### `docker compose up -d --wait` hangs or fails

```bash
docker compose down -v   # destroy volumes, fresh start
docker compose up -d --wait
docker compose ps        # all 6 services should be Up
```

If Postgres is unhealthy: check there's no other Postgres bound to
`:5432` (`lsof -i :5432`).

### Playwright "test report not produced"

Re-run with the JSON reporter explicitly:

```bash
cd tests/playwright && npx playwright test --reporter=json --output playwright-report.json
```

If `playwright-report.json` is still missing, the install is
incomplete: `cd tests/playwright && npm install` and re-try.

### Investigation report shows `Engine abstained — Primary trace not found`

The trace did not flush from the OTel SDK → collector → Jaeger fast
enough. The collector batches every ~5 s. The runners already wait;
if your machine is under load, increase the sleep in
`bin/arip-e2e.sh` from 5 s to 10 s. See
[examples/abstention.md](examples/abstention.md) for what this case
looks like (it is a **feature**, not a bug — we abstain rather than
guess).

### Cross-run "Repeats" column stays at 0

The memory store path is process-relative. The runners now pass
`--memory <repo>/.arip/memory.db` explicitly; if you invoke
`arip investigate` by hand, pass the same flag, or expect each
invocation to start from an empty memory.

### Pool exhaustion test passes when it should fail (SLA invariant met)

The Playwright SLA threshold is 800 ms with `POOL_MAX_CONNS=3` and
`hold_duration=1500ms`. If your machine is very fast and somehow
completes within SLA, lower `POOL_MAX_CONNS` to 2 in
`docker-compose.yml`.

### `uv: command not found`

The demo scripts will fatal-error with this exact message. Install
via the one-liner under Prerequisites, then re-run.

### `docker compose: command not found` (older Docker)

Compose v1 is unsupported. Upgrade to Docker Desktop or install
the Compose plugin: `apt-get install docker-compose-plugin`.

### Anything else

Open an issue or read the layered architecture in
[ARCHITECTURE.md](ARCHITECTURE.md). The engine is ~800 LoC of Python
across five small modules — most issues are reproducible against
`arip-core/tests/` without the live stack.

---

## Investigation lifecycle

A failing test enters at the top; a markdown report and a PR comment
fall out at the bottom. Every box is its own Python module under
[arip_core/](../arip-core/arip_core/).

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Playwright JSON report                                                  │
│  (every test execution, pass or fail, with trace_id + order_id           │
│   annotations from the failing test cases)                               │
└──────────────────────────────────────────────────────────────────────────┘
                              │  parse
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ① FailureEvent          (collector/failure_event.py)                    │
│      one per failing test:                                               │
│      · trace_id        · order_id        · assertion                     │
│      · timestamp       · environment     · stack_trace                   │
└──────────────────────────────────────────────────────────────────────────┘
                              │  correlate
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ② Telemetry Correlation  (correlator/jaeger_client.py + docker_logs)    │
│      · Jaeger /api/traces/<id> with bounded retry on flush latency       │
│      · find sibling traces by `order.id` (cross-trace via business key)  │
│      · `docker logs --since/--until`, JSON-parsed, filtered by trace_id  │
└──────────────────────────────────────────────────────────────────────────┘
                              │  build timeline
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ③ Timeline Reconstruction  (correlator/timeline_builder.py)             │
│      CorrelatedTelemetry =                                               │
│        spans + logs + lifted db_queries + ordered timeline               │
│        + primary_trace_id + related_trace_ids                            │
└──────────────────────────────────────────────────────────────────────────┘
                              │  evaluate
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ④ Rule Evaluation        (engine/hypothesis.py → 5 rules)               │
│      · concurrent_modification  · retry_storm  · downstream_error        │
│      · db_pool_exhaustion       · latency_vs_db                          │
│      each rule = pure function of CorrelatedTelemetry → [Hypothesis…]    │
└──────────────────────────────────────────────────────────────────────────┘
                              │  audit
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑤ Evidence Audit         (engine/evidence_audit.py)                     │
│      every cited span_id/trace_id/log line must exist in telemetry;      │
│      ungrounded evidence dropped, confidence decayed proportionally      │
└──────────────────────────────────────────────────────────────────────────┘
                              │  rank + maybe abstain
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑥ Abstention Check       (engine/abstention.py)                         │
│      bail out via: no_primary_trace · empty_telemetry ·                  │
│                   no_rule_matched · weak_evidence                        │
└──────────────────────────────────────────────────────────────────────────┘
                              │  fingerprint + remember
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑦ Fingerprinting         (memory/fingerprint.py + memory/store.py)      │
│      fingerprint = sha256(rule_id + services + evidence_kinds)[:16]      │
│      lookup history; classify flakiness from per-test pass/fail counts   │
│      persist this investigation for the NEXT run                         │
└──────────────────────────────────────────────────────────────────────────┘
                              │  render
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑧ Report Generation      (reporter/markdown_writer.py + llm_summarizer) │
│      reports/<slug>.md  +  reports/<slug>.json                           │
│      Markdown is deterministic; LLM TL;DR optional + paraphrase-only     │
└──────────────────────────────────────────────────────────────────────────┘
                              │  surface on PR
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ⑨ Delivery               (integrations/github.py + GHA workflow)        │
│      arip-pr-comment.md → sticky comment (header: arip-investigation)    │
│      reports/ + playwright-report.json → arip-reports workflow artifact  │
└──────────────────────────────────────────────────────────────────────────┘
```

Every stage is testable in isolation; the engine layer ⓸–⓺ runs from
synthetic fixtures in `arip-core/tests/` with no live stack.

---

## The five failure patterns

Each pattern has a **deterministic telemetry signature** baked into
the demo services. The rules read those signatures; they do not read
any label the application places to "help" the engine.

### 1. `slow_query` — application-side latency

Injection: inventory-service sleeps 300 ms inside the handler before
touching the DB. Signature: the handler span is slow but
`db.decrement_stock` is fast. Ratio gives it away.
**Rule:** `latency_vs_db`.

### 2. `inventory_error` — downstream 500

Injection: inventory-service returns HTTP 500 with `internal error`.
Payment-service's retry policy treats 500 as **non-retriable** (a
"real bug", not a transient infra glitch), so the upstream sees a
single error and surfaces 502. Signature: one ERROR chain across
two services.
**Rule:** `downstream_error`.

### 3. `webhook_race` — concurrent writes

The (mock) payment processor's webhook arrives in parallel with the
slow-path checkout flow, for the same `order_id`. Both mutate the
same order. Signature: two **separate traces** overlapping in
wall-clock time, both performing `state.transition` events on the
same `order.id`.
**Rule:** `concurrent_modification`. Cross-trace correlation
happens via the `order.id` span attribute.

### 4. `pool_exhaustion` — DB connection pool saturation

Injection: requests hold a checked-out connection while sleeping;
the pool is sized to 3 (`POOL_MAX_CONNS=3`); 6 concurrent requests
fire. Late arrivals stall at `pool.Acquire`. Signature: the
`db.acquire_connection` span carries `db.pool.wait_ms` ≥ 100 and
`db.pool.acquired == db.pool.max`, **while the actual UPDATE query
stays fast**. The DB is healthy; the pool is the bottleneck.
**Rule:** `db_pool_exhaustion`.

### 5. `retry_storm` — request amplification

Injection: inventory-service returns HTTP 503 (a retriable infra
failure). Payment-service's exponential-backoff retry policy kicks
in (max 5 attempts, 0/50/100/200/400 ms). All retries fail.
Signature: five `inventory.reserve_attempt` spans in one trace,
carrying `retry.attempt=1..5`, `retry.backoff_ms=0/50/100/200/400`,
matching `retry.reason` on each. Amplification factor: 5× per
logical request.
**Rule:** `retry_storm` (primary) + `downstream_error`
(alternative — both fire, retry_storm wins by confidence).

A more compact summary lives in [FAILURE_SCENARIOS.md](FAILURE_SCENARIOS.md).

---

## What the output looks like

When you run `bin/arip-e2e.sh`, this is the kind of table that prints:

```
            Investigation summary

  Test                                                  Finding                                       Sev   Conf   Flaky    Repeats
  checkout latency stays within SLA under conc... pool  Database connection pool exhaustion          high  0.93   unknown  0
  checkout returns 200 OK (FAILS under invent... error) Downstream inventory-service failure         high  0.90   unknown  0
  checkout succeeds without exhausting retr... retry)   Retry storm: 5 attempts to `inventory....`   high  0.94   unknown  0
  order transitions stay non-interleaved across traces  Concurrent modification across `checkout...` high  0.92   unknown  0
```

Each row links to a full markdown report. Here is one rendered
report verbatim (trimmed for length):

````markdown
# Investigation Report — checkout succeeds without exhausting retries (FAILS under retry_storm)

## TL;DR
Retry storm: 5 attempts to `inventory.reserve_attempt` in payment-service.
`payment-service` issued 5 attempts of `inventory.reserve_attempt`
against the same downstream in a single trace with exponential
backoff (0ms→50ms→100ms→200ms→400ms). Total wall-time spent in the
retry chain: 763ms. The amplification factor for this one logical
request is 5× — under concurrent load, the downstream sees 5N calls
for N user requests, which can push a marginally degraded service
over the edge.

## Primary hypothesis
### Retry storm: 5 attempts to `inventory.reserve_attempt` in payment-service
- Severity: high · Confidence: 0.94 · Rule: `retry_storm`

**Suggested next step:** Stabilise the downstream first: every retry
hit the same failure, so adding more retries will not help.

**Evidence:**
- `span` — `inventory.reserve_attempt` attempt 1/5 after 0ms backoff — ERROR
- `span` — `inventory.reserve_attempt` attempt 2/5 after 50ms backoff — ERROR
- `span` — `inventory.reserve_attempt` attempt 3/5 after 100ms backoff — ERROR
- `span` — `inventory.reserve_attempt` attempt 4/5 after 200ms backoff — ERROR
- `span` — `inventory.reserve_attempt` attempt 5/5 after 400ms backoff — ERROR
- `span` — Each attempt hit `inventory-service.inventory-service` ERROR:
  HTTP 503. The downstream was consistently failing — retries are the
  symptom, the downstream is the root cause.
- `log` — inventory: reserve failed
- `log` — inventory: reserve failed                       (×4 more)
- `log` — payment: reserve failed
````

Three things are worth noting about that output:

1. **Every claim is grounded.** Each `span` evidence line carries a
   trace_id + span_id; each `log` line was actually present in
   docker logs. The audit layer (`engine/evidence_audit.py`) drops
   any cited reference that does not exist in the telemetry.
2. **The "next step" is specific.** It does not say "investigate
   inventory-service". It says "stabilise the downstream first;
   retries amplified load by 5×".
3. **There is no AI guessing here.** The text is generated from the
   rule's deterministic output. The optional LLM TL;DR is a strict
   paraphrase of the same content; with no API key it falls back to
   a deterministic prose line.

---

## Cross-run intelligence

Every report carries a **fingerprint** that is independent of trace
IDs, order IDs, and timestamps:

```
fingerprint = SHA256(
    rule_id
    + sorted(service names from evidence)
    + sorted multiset of evidence kinds {span:5, log:6, span_event:0}
)[:16]
```

Run the demo twice. The second run's reports will include:

```
## Cross-run context

This same root-cause shape has been seen 1 time(s) by ARIP
(1 of them in the last 14 days). Fingerprint: `193713f185d4ac66`.

- First observed: 2026-05-19T08:55:24+00:00
- Most recent:    2026-05-19T08:55:24+00:00
```

The fingerprint is what would let a real deployment say "this is the
7th time this PR family has caused a retry storm" or "this pattern
appeared in main two weeks ago".

It is stored in `.arip/memory.db` (SQLite). In CI the file is cached
across runs via `actions/cache` so the history accumulates over the
life of the repository.

---

## When ARIP refuses to guess

The engine deliberately abstains in four situations:

| Code                | Condition                                                                     |
|---------------------|-------------------------------------------------------------------------------|
| `no_primary_trace`  | The trace ID from the failing test never appeared in Jaeger (sampled, lost).  |
| `empty_telemetry`   | No spans or logs available for the failure window.                            |
| `no_rule_matched`   | The telemetry shape did not match any deterministic rule's signature.         |
| `weak_evidence`     | Top hypothesis has confidence < 0.7 or fewer than 2 evidence kinds.           |

Sample abstention block (from a report where the trace was lost):

```markdown
## ⚠️  Engine abstained

**Primary trace not found in the telemetry backend.**

The failure carries a trace_id but no spans for that trace were
retrievable from Jaeger after a bounded retry. The trace may have
been sampled out, lost in the pipeline, or not yet flushed by the
SDK. Without the primary trace, any hypothesis would be speculative.

Diagnostics:
- `expected_trace_id` = `e8e72b08...`
- `related_trace_ids` = `[]`
- `spans_seen` = `0`
```

This is the property that separates a useful investigator from a
confident-sounding one: **the willingness to say "I don't know".**

---

## Tail-based sampling strategy

A single OTel Collector sits between the demo services and Jaeger.
Its job is to **never throw away a trace that ARIP needs**.

Always-keep policies (`demo-env/otel-collector/config.yaml`):

| Policy            | Keeps every trace where…                                |
|-------------------|---------------------------------------------------------|
| `keep-errors`     | any span has `status=ERROR`                             |
| `keep-slow`       | end-to-end duration ≥ 250 ms                            |
| `keep-explicit`   | any span carries `arip.force_sample=true`               |
| baseline          | 5% random sample of everything else                     |

The Playwright suite sends `X-Arip-Capture: true` on every request.
The demo services attach `arip.force_sample=true` to their root span
when they see that header — so all test traces survive sampling
end-to-end, including the fast OK ones (e.g. the webhook side of
the `concurrent_modification` scenario).

In a real deployment customers would lower the baseline to 1–2%; the
error/slow/explicit policies remain useful guarantees regardless.

---

## Why deterministic RCA

A common alternative is "ask the LLM to read the logs and tell us
what happened". ARIP intentionally does not work that way.

| Property              | LLM-driven RCA                              | Deterministic RCA (ARIP)                                |
|-----------------------|---------------------------------------------|---------------------------------------------------------|
| Reproducibility       | Output varies run to run                    | Same telemetry → same output, byte-identical            |
| Auditability          | Hard — model decides what mattered          | Every citation maps to a real span/log/event            |
| Confidence calibration| Confidence is a vibe                        | Computed from objective signal strength                 |
| Abstention            | LLMs rarely say "I don't know"              | Engine bails out by design when signal is thin          |
| Cost per investigation| Token cost × prompt size × trace volume     | Pure compute on already-collected telemetry             |
| New failure pattern   | "Maybe the model will figure it out"        | Write a rule; ship unit tests; deterministic behaviour  |

The LLM still has a job — paraphrasing the deterministic finding into
a 2-4 sentence TL;DR. It is given *only* the deterministic output, with
explicit instructions not to introduce new claims. Without an API key
it falls back to a deterministic prose line.

---

## Where the MVP boundary is

This MVP is intentionally narrow. Here is the same scope table from
the README, for the readers who jumped straight to this doc:

| ✅ MVP scope today                                                  | 🚫 explicitly NOT in scope                                  |
|---------------------------------------------------------------------|-------------------------------------------------------------|
| Local-first, Docker Compose                                         | Generic APM / observability vendor replacement              |
| Playwright-focused failure ingestion                                | AI-driven hypothesis generation (LLM-as-engine)             |
| Deterministic rule-based investigation                              | Auto-remediation / self-healing / runbook execution         |
| Post-failure investigation (read-only)                              | Deterministic replay / time-travel debugging                |
| Evidence-grounded, auditable reports                                | Full distributed-causality engine                           |
| GitHub Actions sticky PR comment                                    | Jira / Slack / PagerDuty / external integrations            |
| Cross-run fingerprinting + flaky classification                     | Broad connector ecosystem (focus over coverage)             |
| OTel application-layer telemetry                                    | eBPF / kernel / service-mesh signals                        |

Triggers for relaxing any of these constraints live in
[FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md). The phased plan is
in [ROADMAP.md](../ROADMAP.md).

## Known limitations

Honest list (overlaps with the right column above; this is the
engineering view rather than the product view):

- **Deterministic replay** is not implemented. ARIP gives you the
  root cause; it does not give you a time-travel debugger.
- **Causal inference vs correlation.** When two traces share an
  `order.id` and overlap in time we call it "concurrent modification".
  In strict happens-before terms this is correlation, not proof of
  causation. Acceptable for the patterns shipped; documented.
- **No statistical baselines.** Latency rules use hard thresholds
  (`50 ms`, `10× ratio`, …) rather than per-endpoint p99. Fine for
  the demo; insufficient for production heterogeneity.
- **No service mesh / eBPF / kernel telemetry.** Failures invisible
  to OTel application-layer instrumentation are invisible to ARIP.
- **Confidence numbers are heuristic, not calibrated.** They reflect
  the strength of corroborating signals, not historical accuracy
  against ground truth (we have no labelled outcomes yet).
- **No regression test generation.** The report tells you *what*
  failed; it does not synthesise a test to lock the fix in.

Triggers and rough sketches for lifting these are in
[FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md). They are
**explicitly out of MVP scope.**

---

## Reference

- [ARCHITECTURE.md](ARCHITECTURE.md) — module boundaries
- [INVESTIGATION_RULES.md](INVESTIGATION_RULES.md) — what each rule does and how to add one
- [FAILURE_SCENARIOS.md](FAILURE_SCENARIOS.md) — telemetry signature per scenario
- [FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md) — what is deliberately not built
- [../README.md](../README.md) — repo-level overview and quick start
- [../.github/workflows/arip-investigate.yml](../.github/workflows/arip-investigate.yml) — CI integration

## You are here

If you got this far, you have seen everything the MVP does. The
right next steps are usually one of:

1. Open a Pull Request against this repo — the GitHub Actions
   workflow will run end to end and post the sticky comment.
2. Add a sixth failure scenario + rule. Pattern: emit a new
   telemetry signature from the demo services, write a rule that
   reads it, ship unit tests in `arip-core/tests/`.
3. Point the correlator at your own Jaeger / Tempo / Loki and try
   investigating one of your real test failures. The clients in
   `arip_core/correlator/` are small and pluggable.
