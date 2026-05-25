# Quickstart — 15 minutes, clone → working demo

The shortest path from `git clone` to seeing ARIP investigate a real
Playwright failure. If you only have 15 minutes, this is what to run.

## Prerequisites (2 minutes)

| Tool             | Min version | Install                                                   |
|------------------|-------------|-----------------------------------------------------------|
| Docker + Compose | recent      | Docker Desktop (mac/win) or `docker-engine` + plugin (linux) |
| Node             | 20.x        | `nvm install 20` / `brew install node@20`                 |
| `uv`             | 0.5+        | `curl -LsSf https://astral.sh/uv/install.sh \| sh`        |

You also need `curl` and `python3` for the demo scripts — both are
on every recent macOS / Linux by default.

## Demo (5 minutes)

```bash
git clone <repo-url> arip
cd arip
bin/arip-demo.sh
```

That's it. The runner:

1. Preflights your toolchain — fatal-errors with a one-liner if
   anything is missing.
2. Self-bootstraps — runs `npm install` and `uv sync` on first use.
3. Brings up the Docker Compose stack (Jaeger + OTel Collector +
   Postgres + Redis + payment-service + inventory-service).
4. Resets the inventory so the demo is reproducible.
5. Runs the Playwright suite. One test passes, four fail by design.
6. Investigates each failure with the deterministic engine.
7. Re-runs to demonstrate cross-run fingerprinting.
8. Renders the GitHub-style PR comment.

End-to-end: ~30 seconds on a recent laptop.

## What you'll have at the end (3 minutes to inspect)

```
arip/
├── reports/                    8 markdown investigation reports
│   └── *.md                    one per failure, per run (4 × 2)
├── arip-pr-comment.md          consolidated sticky-PR-comment view
└── .arip/memory.db             SQLite memory: 4 fingerprints, 10 test runs
```

Open any one report — they all follow the same structure:

```
# Investigation Report — <test name>

## TL;DR              ← 2–4 sentence summary
## Cross-run context  ← "seen 1 time(s) before · fingerprint abc…"
## Flaky-test signal  ← ✅ stable | 🎲 flaky | ❔ unknown
## Failure            ← test, trace_id, order_id, assertion
## Primary hypothesis ← title · severity · confidence · rule
                        + description + suggested next step
                        + cited Evidence (span_ids, log lines)
## Alternative hypotheses (if any)
## Request timeline   ← spans + logs + DB queries, sorted by time
## Evidence index     ← clickable Jaeger trace links
```

Also worth opening:

- `arip-pr-comment.md` — the consolidated view a CI/CD pipeline would
  post on a PR.
- Jaeger UI: <http://localhost:16686> — every report links into the
  correct trace.

## Verify the 5 failure patterns (5 minutes)

The Playwright suite covers four of them; `slow_query` is exercised
manually via the failure-injector script.

```bash
# baseline (passes)
# → no report; investigation only runs over failures.

# webhook_race → concurrent_modification (high, conf 0.92)
cat reports/order-transitions-stay-non-interleaved-across-traces-*.md

# pool_exhaustion → db_pool_exhaustion (high, conf 0.93)
cat reports/checkout-latency-stays-within-sla-under-concurrent-load-*.md

# retry_storm → retry_storm (high, conf 0.94) + downstream_error alt
cat reports/checkout-succeeds-without-exhausting-retries-*.md

# inventory_error → downstream_error (high, conf 0.90)
cat reports/checkout-returns-200-ok-fails-under-inventory-error-*.md

# slow_query (not in Playwright suite — exercise manually):
./demo-env/failure-injector/scenarios/slow_query.sh
```

Each report stands alone: the cited Evidence either points at a real
span_id / trace_id (resolved against live Jaeger) or a real log line
(resolved against `docker logs`). Nothing fabricated.

## Stop the stack

```bash
docker compose down -v
```

## Where to go next

| You want to…                                    | Read this                                            |
|-------------------------------------------------|------------------------------------------------------|
| Understand what ARIP is and why it exists       | [docs/ARIP_DEMO_WALKTHROUGH.md](docs/ARIP_DEMO_WALKTHROUGH.md) (15 min) |
| See the rule registry + abstention contract     | [docs/INVESTIGATION_RULES.md](docs/INVESTIGATION_RULES.md)             |
| See per-scenario telemetry signatures           | [docs/FAILURE_MATRIX.md](docs/FAILURE_MATRIX.md)                       |
| Read curated example outputs without running    | [docs/examples/](docs/examples/)                                       |
| Know what is intentionally NOT built            | [docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md)             |
| See the phased roadmap                          | [ROADMAP.md](ROADMAP.md)                                               |
| Run ARIP in GitHub Actions on a real PR         | [.github/workflows/arip-investigate.yml](.github/workflows/arip-investigate.yml) |
| Run **observe-mode** against your own telemetry | [docs/OBSERVE_MODE.md](docs/OBSERVE_MODE.md) + [docs/INGESTION_GUIDE.md](docs/INGESTION_GUIDE.md) |
| Pilot observe-mode with a real engineer         | [docs/OBSERVE_PILOT_KIT.md](docs/OBSERVE_PILOT_KIT.md) + `bin/run-observe-pilot.sh` |

## If anything went wrong

See the **Troubleshooting** section near the bottom of the
[walkthrough](docs/ARIP_DEMO_WALKTHROUGH.md). The most common cases:

- Demo stack hangs → `docker compose down -v && docker compose up -d --wait`
- Engine abstained ("Primary trace not found") → bump the flush sleep
  in `bin/arip-e2e.sh` from 8s to 12s for slow machines
- `uv: command not found` → install via the one-liner above

If you hit something not covered there, ARIP's whole engine is ~800
lines of Python across 5 small packages — reproducible against
`arip-core/tests/` without the live stack.
