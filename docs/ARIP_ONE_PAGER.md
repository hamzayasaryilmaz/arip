# ARIP — one-pager

> Print this. Leave it on the CTO's desk. That's the entire collateral
> you need.

## What it is

**ARIP** (Autonomous Reliability Investigation Platform) is an
open-source deterministic CI investigation engine. When a Playwright
or Cypress test fails in your CI pipeline, ARIP reads your existing
OpenTelemetry telemetry, applies five fixed rules, and produces a
markdown report that says either *"most likely cause: X, here are
the cited spans + logs that support it"* or *"I don't know, here's
why"*.

No AI in the analysis path. No guessing. The same input always
produces the same output.

## What it does that's different

| Most "AI RCA" tools | ARIP |
|---|---|
| Always produces an answer | Produces an answer OR honest abstention |
| Confidence reported as a number you can't verify | Confidence backed by cited evidence you can open in Jaeger |
| LLM in the analysis path | LLM only paraphrases the TL;DR; never touches raw telemetry |
| "We support all observability vendors" | One good OTel + Jaeger/Tempo + Loki/ES path |
| Pricing model: per-team-per-month SaaS | Apache-2.0 OSS; pay for integration consulting |
| Dashboard | Markdown report → sticky GitHub PR comment |

The moat is **honesty**, not technology.

## What it deliberately is NOT

- Not an APM (Datadog, Honeycomb, New Relic) — it **reads from** them
- Not a dashboard
- Not an alerting tool — produces no notifications
- Not autonomous — opens no PRs, takes no action
- Not "self-healing" — tells you what it sees; you decide what to do
- Not a generic "AI for engineering" platform

## What it requires

| | |
|---|---|
| Distributed tracing | OpenTelemetry (or Zipkin-compatible) propagating `trace_id` across services |
| One supported trace backend | Jaeger, Tempo, or Elasticsearch (APM-shape spans) |
| Optional: log backend | Loki or Elasticsearch (logs joined by trace_id, makes rules fire more often) |
| Test framework | Playwright or Cypress |
| Compute | Local laptop, Docker, or GitHub Actions runner — no infrastructure needed |

Without distributed tracing, ARIP cannot help. The prerequisite
gate will tell you exactly what's missing.

## The five rules

| Rule | Fires when |
|---|---|
| `retry_storm` | A client retried the same operation 2+ times with consistent failure |
| `db_pool_exhaustion` | DB connection pool saturated, requests queued waiting |
| `downstream_error` | An ERROR span chain crossed a service boundary |
| `concurrent_modification` | Two traces touched the same business key with conflicting state transitions |
| `latency_vs_db` | Handler latency dominated by a slow DB span |

Anything outside these five → ARIP abstains. Honestly.

## Five abstention codes

| Code | What it means |
|---|---|
| `no_primary_trace` | Promised trace didn't show up in Jaeger (sampling/flush) |
| `empty_telemetry` | No data in the window |
| `no_rule_matched` | None of the 5 rules apply to this telemetry shape |
| `weak_evidence` | A rule almost fired but evidence is below the trust threshold |
| `conflicting_hypotheses` | Two rules fire on disjoint evidence at similar confidence |

Each abstention carries an actionable next-step pointing at the
specific telemetry-hygiene action that would close the gap.

## Validation status

- **223/223 unit tests passing** locally + on GitHub Actions CI
- **5 unknown-OSS-system validations** completed (Jaeger HotROD,
  CNCF OpenTelemetry Demo + fault injection + Loki join, Grafana
  Tempo). One milestone: rule cluster fired correctly on a system
  the engine had never seen, end-to-end through 3 separate OSS
  backends (OTel Demo + Jaeger + Loki).
- **Zero false-high-confidence outcomes** across all validation
- **Two real defects** caught during validation, both narrowly fixed
  with regression tests
- **No real-engineer pilot yet** — that's what the paid pilot
  engagement offers solve for

## Honest gaps

- Async messaging (Kafka, SNS, RabbitMQ) — not in scope yet; ARIP
  abstains on traces that cross async boundaries
- 5 rules is intentionally narrow; some teams will see 80%
  abstention until/unless they extend the rule set
- Requires distributed tracing — logs-only setups cannot use ARIP

## How to evaluate it

Three concrete paths, ordered by commitment:

1. **5 minutes — read the engineering rationale.** Start with
   `docs/POSITIONING.md` on GitHub. If the trust-contract framing
   resonates, continue. If "we hand-roll five rules and refuse to
   guess" sounds limited, ARIP isn't a fit for you.

2. **30 minutes — try the demo.**
   `git clone https://github.com/hamzayasaryilmaz/arip && cd arip && bin/arip-demo.sh`
   Spins up a Docker stack, runs 4 failing Playwright tests,
   produces 8 markdown reports. End-to-end in 30 seconds.

3. **2 weeks — paid pilot against your own telemetry.**
   $5,000–$10,000. Working integration + telemetry hygiene audit
   report. Audit is valuable on its own. Recommended starting
   engagement.

## Contact

[your name + email + GitHub handle]

The repo: https://github.com/hamzayasaryilmaz/arip
Apache-2.0, no commercial license — pay for services around it,
not the software.

---

*Document version: 1.0 · Project: v0.1.0 · pre-first-paying-customer*
