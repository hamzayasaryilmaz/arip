# ARIP, explained for someone curious but new

A plain-English walkthrough for someone who has never heard of
OpenTelemetry, tracing, or root-cause analysis, but is curious
about software engineering and willing to learn. No assumed
background. No buzzwords.

If you already know what spans and trace_ids are, skip to
[*"What ARIP actually does"*](#what-arip-actually-does).

---

## The problem ARIP is built around

You write some code. It works on your machine. You ship it. A few
days later, a test in your continuous-integration (CI) pipeline
starts failing. Sometimes. Not every time. The error message is
something like *"checkout took 7 seconds, expected under 2"*.

You log in. You stare at the failing test. You start asking:

- *Why is checkout slow now?*
- *Was it always slow, or did it just start?*
- *Is the database slow? The payment service? The third-party API?*
- *Did anyone deploy something near when this started?*
- *Or is this just "the test is flaky"?*

To answer these you need to **piece together what was happening
across many different parts of the system at the moment of the
failure**. That is the hard part. Modern apps aren't one program
running on one computer. A single user click can touch 5, 10, 50
different services, each running in its own container, each
writing its own log file, each touching its own database.

When that click fails, the evidence of *why* is scattered across
all of those places. Finding it manually is detective work.

ARIP is the thing that does the detective work for you, *one
narrow class of failure at a time*. The goal is not to magically
fix bugs — the goal is to hand you a short report that says:

> *Most likely cause: your database connection pool was saturated.
> Here are the exact log lines and traces I'm basing that on. Open
> them and verify before you do anything.*

That's it. That's the whole product. The interesting part is
**how** it does this without making things up, and **when** it
refuses to even try.

---

## Five concepts you need first

Most of this doc uses these five words. Quick definitions, no
pretending they're obvious.

### 1. Log

A line of text a program writes when something happens. Example:

```
2026-05-25 11:23:01  ERROR  payment-service  could not reserve item: out of stock
```

Useful when you can find the right one. Not useful when there are
millions of them per hour and they don't tell you what was
happening at the same time elsewhere.

### 2. Trace

A *trace* is the record of one request as it travels through your
system. If a user clicks "Buy Now" and that click hits the
frontend, then the payment service, then the inventory service,
then a database — the trace is the record of all four of those
things happening, with how long each one took.

A trace has a unique `trace_id` (a long random-looking string) so
you can correlate everything related to that one request.

### 3. Span

A trace is made of **spans**. One span = one piece of work inside
a trace. The "frontend handled the click" is a span. The "payment
service called inventory" is another span. The "database query"
is another span.

Each span has a start time, a duration, a service name (which
piece of the system did it), an operation name (what kind of
work), and attributes (extra structured data like
`http.status_code: 500`).

### 4. OpenTelemetry (OTel)

The standard that makes spans portable. If you instrument your
code with OpenTelemetry, you can send those spans to any compatible
storage backend — Jaeger, Tempo, Honeycomb, Datadog, etc. — and
the data shape is the same. ARIP reads OpenTelemetry data;
specifically, it reads it from Jaeger (and supports being
extended to others via small adapter scripts).

### 5. Root cause analysis (RCA)

Investigating *why* a failure happened, not just *that* it
happened. "Test failed because checkout took 7 seconds" is
description. "Test failed because the database connection pool
saturated under concurrent load and request 4 waited 1.5 seconds
for a connection" is root-cause analysis.

The investigation that turns the first sentence into the second
is what ARIP automates.

---

## Why this is genuinely hard

Three reasons engineers don't enjoy this work:

1. **The evidence is scattered.** Logs are in one place, traces
   in another, database metrics in a third, deployment history in
   a fourth. A single failure needs evidence from all four.

2. **Your test runs many times.** "Yesterday checkout took 2 seconds,
   today it took 7" — was it the database? The deploy two hours
   before? Some unrelated noisy neighbour on the same Kubernetes
   node? You need to compare runs.

3. **The signal is buried in noise.** Most logs are uninteresting.
   Most spans are fast and successful. The interesting ones — the
   ones that explain the failure — are a handful out of thousands.

This is the niche where many tools have tried to use AI to "find
the root cause for you". Many of them get it confidently wrong.
ARIP is built around the observation that **a confidently wrong
answer is much worse than no answer at all** — a wrong answer
sends an engineer in the wrong direction, often for hours.

---

## What ARIP actually does

ARIP has two modes. They share the same engine.

### Mode 1 — Investigation (per-failure)

A test in CI fails. ARIP picks up the failure, gathers the
relevant telemetry from your existing OpenTelemetry tracing setup
(Jaeger + your container logs), runs **five fixed rules** over the
data, and emits a single markdown report explaining what most
likely caused the failure.

The five rules are:

| Rule | What it claims, in one sentence |
|---|---|
| `retry_storm` | "Your client retried the same call many times in a row — that's amplifying load, not solving the underlying failure." |
| `db_pool_exhaustion` | "Your database connection pool is saturated; requests are queued waiting for connections." |
| `downstream_error` | "An error in service A bubbled up through service B and caused the failure you saw." |
| `concurrent_modification` | "Two requests touched the same business object at the same time in an unexpected way." |
| `latency_vs_db` | "The handler is slow because the database query inside it is slow." |

Each rule cites the specific spans and log lines that support its
claim. You can open Jaeger and verify them by hand. Nothing is
fabricated.

If none of the five rules fit — or if the evidence is too thin —
ARIP produces an **abstention** instead of a guess. More on this
in a moment, because it's the most important part.

### Mode 2 — Observation (continuous, optional)

You point ARIP at a window of telemetry — last hour, last day,
last week — and it tells you *which anomaly patterns are recurring*
across many traces.

Example output: *"Across 1,200 traces in the last 24 hours, the
retry_storm pattern recurred 47 times on the checkout flow. Here
are the trace IDs."*

This is the same engine, just pointed at a stream of past traces
instead of a single failing CI test. It does not generate alerts,
open tickets, or write code. It produces a digest you read.

---

## The thing that makes ARIP different — abstention

When ARIP can't confidently identify a root cause, it **says so**.
There are five abstention codes:

| Code | What it means in human terms |
|---|---|
| `no_primary_trace` | "I was told a request failed, but I can't find the trace for it. The telemetry pipeline probably dropped it." |
| `empty_telemetry` | "There's no data in the time window. Either nothing happened, or your telemetry isn't flowing." |
| `no_rule_matched` | "I looked at this trace, and none of my five rules apply. I don't have a guess for you." |
| `weak_evidence` | "I have a possible answer, but I'm not confident enough to promote it as the primary cause. Look at it as a hint, not a verdict." |
| `conflicting_hypotheses` | "Two different rules want to fire, on different parts of the trace, at similar confidence. Picking one would send you the wrong way." |

This list is **the moat**. Most tools that look like ARIP do not
abstain — they always produce a "most likely cause", even when
the data doesn't support one. Engineers learn quickly that those
tools cry wolf, then stop trusting them. ARIP's contract is:
*if I'm going to be wrong, I will refuse to answer instead.*

The trade-off is honest: you sometimes get *"I don't know"*
instead of *"I have a guess"*. In exchange, when ARIP does
produce a primary cause, you can act on it.

---

## Why "deterministic" matters here

Two words that get conflated in tools like this: **deterministic**
and **AI-based**.

- **Deterministic** = if you give me the same input, I will
  produce the same output, every time. The reasoning path is
  inspectable. The same input today gives the same answer next
  year.

- **AI-based** (large-language-model-based) = the model is a
  black box that produces plausible-sounding text. Same input can
  produce different output. Hallucinations are a known failure mode.

ARIP is **deterministic in its analysis path**. The five rules are
plain Python code. Each rule reads telemetry, checks a fixed
pattern, computes a confidence number from a fixed formula, and
either emits a hypothesis or doesn't.

A language model is involved in *exactly one place*: writing the
2-4 sentence "TL;DR" at the top of the report, paraphrasing what
the deterministic engine already found. It never sees raw
telemetry. It cannot influence the verdict. If you don't set an
API key, ARIP runs without the LLM entirely — the report is just
slightly less friendly.

This is not "AI investigates your bug". This is "an engine
inspects telemetry against five clearly-written rules, and a
language model writes the cover letter."

---

## What ARIP is NOT

Be honest about scope:

- **Not a monitoring dashboard.** No graphs, no live view, no
  always-on UI.
- **Not an alerting tool.** It does not page anyone. It does not
  send Slack messages.
- **Not an APM** (Application Performance Monitoring) tool. It
  doesn't compete with Honeycomb, Datadog, Grafana.
- **Not an autonomous agent.** It does not open PRs, write code,
  fix bugs, restart services, or take any other action without
  you.
- **Not a self-healing platform.** It tells you what it sees. You
  decide what to do.
- **Not magic.** When the telemetry is thin, the engine abstains.
  Garbage in → honest "I don't know" out.

These exclusions are deliberate. The project's strategy doc
([POSITIONING.md](POSITIONING.md)) treats each one as an
**anti-goal** — any change that would drift toward one of them
gets rejected at design review.

---

## How an engineer actually runs it

Three real workflows, each one is one command.

### Workflow A — Try the demo in 30 seconds

```bash
git clone https://github.com/hamzayasaryilmaz/arip.git
cd arip
bin/arip-demo.sh
```

This brings up a small Docker Compose stack with two example
services (payment-service, inventory-service) instrumented with
OpenTelemetry, runs four Playwright tests that fail by design,
investigates each failure with ARIP, and prints a summary. End
to end: about 30 seconds.

After it finishes you'll have:
- 8 markdown reports in `reports/` (4 failures × 2 runs)
- A consolidated `arip-pr-comment.md` showing what GitHub would
  post on a PR
- A `.arip/memory.db` SQLite database with cross-run fingerprints

### Workflow B — Check if your own telemetry is ingest-able

```bash
bin/observe-self-audit.sh /path/to/your/telemetry.jsonl
```

If you already have OpenTelemetry traces exported as JSONL
(JSON-lines), this command runs ARIP against the first 5 traces
in a throwaway store and prints a digest. You'll see what
quality band your telemetry lands in, which rules fire, and which
abstain. Takes about 30 seconds. Throws away its results.

If you don't have JSONL yet but you do have Jaeger, the
[INGESTION_GUIDE.md](INGESTION_GUIDE.md) shows how to convert in
one command via `bin/jaeger-export-to-bundles.py`.

### Workflow C — Run a real pilot session

```bash
bin/run-observe-pilot.sh /path/to/telemetry.jsonl op002
```

This scaffolds an archive directory at
`docs/observe-pilot-archive/op002/`, runs the self-audit, runs
the full observation, writes the digest, and prints what to do
next: open the digest in front of an engineer, sit quietly, watch
how they read it, fill in three templates with their verbatim
words. Used in real pilots, not for solo runs.

The [OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md) is the full
operator guide — about a 5-minute read.

---

## What the project has actually proven, vs what it hasn't

Honest classification of where the project stands today
([v0.1.0](https://github.com/hamzayasaryilmaz/arip/releases/tag/v0.1.0)):

### Proven

- The deterministic engine works on the five built-in scenarios:
  the demo produces the expected reports reproducibly across runs
- The trust contract (abstention discipline) holds under synthetic
  noisy telemetry — see
  [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md)
- Observation mode handles real OpenTelemetry export shapes
  (Jaeger JSON, Loki streams) — see same doc, Appendix B
- The engine produced **zero false-high-confidence outcomes**
  against a real OSS system it had never seen (Jaeger HotROD
  demo) — see [HOTROD_FINDINGS.md](HOTROD_FINDINGS.md)
- 145 unit tests pass on a fresh public clone of the repo
- The GitHub Actions workflow runs successfully on GitHub-hosted CI

### Still hypothesis

- That a real human engineer, looking at the digest of their own
  telemetry, will find it useful enough to want to run again next
  week. This is what the first real pilot (`op002`) is supposed
  to test.
- That the rule contracts cover enough real-world failure shapes
  to be valuable across teams. So far they cover five shapes —
  that is a starting point, not a comprehensive set.
- That cross-run memory (fingerprinting) produces signal that
  changes engineers' behavior. The mechanism works; whether
  anyone acts on it is unproven.

### Genuinely unknown

- How the engine behaves under telemetry from systems with very
  different domain shapes (event-sourcing, async message queues,
  serverless). All current validation is request-response shaped.
- What happens at >10,000 traces per pilot run. The store is
  bounded, but performance characteristics at scale haven't been
  measured.
- Whether the QA/regression-assistance roadmap
  ([FUTURE_ARCHITECTURE.md #11](FUTURE_ARCHITECTURE.md)) is the
  right direction. It's gated to trigger conditions; if those
  aren't met, the capability stays in a doc, not in code.

---

## Where this is in its lifecycle

Think of ARIP as a **research-grade engineering tool** at v0.1.0
that has just had its first synthetic-noisy and real-OSS validation
passes, but has not yet had a real engineer sit with it on their
own system. The next step is exactly that.

Concretely: if you want to be the first real user, the recruitment
package and the operator briefing are both ready
([observe-pilot-recruitment.md](observe-pilot-recruitment.md),
[OBSERVE_OPERATOR_BRIEFING.md](OBSERVE_OPERATOR_BRIEFING.md)) —
30 minutes of your time produces useful data for the project and
gives you back an honest assessment of your telemetry hygiene.

If you don't want to be a user, but you're interested in the
design choices, the most useful reads are:

- [POSITIONING.md](POSITIONING.md) — the strategy that gates
  what gets built and what gets refused. The decision-gate
  itself is the artefact.
- [HOTROD_FINDINGS.md](HOTROD_FINDINGS.md) — what happened when
  the engine met a system it had never seen, told honestly.
- [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) — what the
  validation suite actually catches, including the two real
  defects it caught during validation.

---

## One sentence summary

> *ARIP is a deterministic engine that reads OpenTelemetry traces,
> applies five fixed rules, and produces either an evidence-grounded
> report or an honest "I don't know" — never a confident guess that
> isn't backed by data.*

Everything else in the project flows from that sentence. If a
proposed change weakens any of the five clauses (deterministic /
existing OTel traces / fixed rules / evidence-grounded / honest
abstention) it gets refused at design review. That's the discipline,
and it is the whole reason the project is worth taking seriously.
