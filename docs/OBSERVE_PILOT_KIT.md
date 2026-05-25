# Observe-mode pilot kit

This is the operator-facing kit for the **first real telemetry pilot**
of `arip observe` (Phase A). It is deliberately separate from the
investigation-mode pilot kit ([PILOT.md](../PILOT.md)) because the
two capabilities ask the operator different questions.

Investigation mode asks: *"can ARIP help me find the root cause of
this one failing test?"* Observation mode asks: *"can ARIP help me
see which anomaly patterns are recurring in my telemetry?"*

This kit covers the second question only.

## What this pilot is for

A single, narrow purpose:

> Run `arip observe` against a real engineer's real CI / staging
> telemetry, then sit with the engineer while they read the digest,
> and capture honestly whether it was useful.

It is **not** for:

- Generating reproduction-candidate tests (Phase A does not do this)
- Drafting PRs (Phase A does not do this)
- Replacing your existing observability stack
- Producing alerts or paging anyone
- Demonstrating ARIP's "AI capabilities" (there are none in this path)

If a pilot conversation drifts toward any of the above, gently bring
it back. The honesty bar is: *"does observe-mode give an engineer
something they can act on, from telemetry they already have?"*

## Off-limits during the pilot

These are the same off-limits as the investigation pilot, plus a
few observe-mode specific ones:

- Do NOT modify any rule mid-pilot. If a rule abstains where the
  engineer thinks it should fire, note it as feedback — do not
  re-tune.
- Do NOT lower any abstention threshold. The trust contract is part
  of what's being validated.
- Do NOT add a new abstention code, even if the pilot surfaces a
  shape that fits awkwardly into the existing five.
- Do NOT add candidate generation, template generation, sandbox
  validation, PR opening, alerting, or any kind of dashboard. These
  are explicitly frozen and trigger-gated. See
  [FUTURE_ARCHITECTURE.md #11](FUTURE_ARCHITECTURE.md).
- Do NOT relax the per-source cursor contract or auto-detect file
  rotation. The pathology of in-place rotation is documented
  ([TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) Pre-pilot P3);
  the workflow workaround is what gets exercised in this pilot.
- Do NOT change the digest "What this digest is NOT" disclaimer.
  Even if the operator finds it tedious.

If the pilot exposes a real bug or trust regression, capture it in
`feedback.md` and stop the pilot. Don't patch live.

## Minimum-friction operator workflow

Target time-to-first-digest: **≤ 30 minutes** from "I have an
ARIP checkout" to "I have a digest on screen."

```
clone repo → uv sync → install adapters (already in bin/)
            ↓
pre-pilot telemetry checklist (10 min — section below)
            ↓
pull one window of telemetry (Jaeger, Loki, GHA artifact, or jsonl)
            ↓
convert with bin/ adapter if needed
            ↓
arip observe <bundles.jsonl> --store .arip/observation.db
            ↓
read digest, fill operator-notes.md
```

### Step 1 — Pre-pilot telemetry checklist

Before pulling any telemetry, confirm your environment can produce
the minimum signals ARIP observe-mode needs. None of these are
optional: if you do not have them, the pilot will produce an
abstention-heavy digest and you will learn nothing actionable
about anomaly clustering.

| Signal | Why ARIP needs it | How to check yours has it |
|---|---|---|
| OpenTelemetry traces with stable `trace_id` | The unit of clustering. Without it, every observation is a singleton | One end-to-end CI request shows up in Jaeger with `≥ 2` spans across `≥ 2` services |
| Span `status` reflects errors | Engine reads `span.is_error`; HTTP 5xx without OTel ERROR status confuses correlation | An intentionally-failing request produces a span with `otel.status_code=ERROR` |
| Structured logs (JSON-shaped or with `trace_id` field) | Without log evidence the engine often abstains with `weak_evidence` | A log line for the failing request carries a resolvable `trace_id` |
| Per-failure `trace_id` recoverable from the test or response | So the pilot can correlate one failure to one trace bundle | A failed Playwright/Cypress test report or HTTP response carries the trace_id |

If 3 of 4 hold, proceed. If only 1–2 hold, fix telemetry hygiene
first; running observe against thin telemetry is not a meaningful
trust signal — it's a telemetry-hygiene signal. Tell the pilot
participant honestly.

**Additionally — naming-convention check.** ARIP's default config
(`arip-core/configs/demo.yaml`) sets
`handler_operation_patterns: ['handle_']`. If the pilot system's
HTTP/RPC handler operation names do **not** contain the substring
`handle_`, the `latency_vs_db` rule will silently abstain because
it can't identify entry-point spans. Quick check: list 5–10
operation names from a representative trace; if none contain
`handle_`, add a config override per
[docs/ONBOARDING.md](ONBOARDING.md) ("Writing your config" section)
before the pilot. Common needed overrides:

- Spring controllers → `['Controller#']`
- Go HTTP routers   → endpoint patterns like `['/api/', '/v1/']`
- gRPC services     → method substrings like `['Service/']`

This pathology was observed during op001 (HotROD warm-up) — see
[docs/observe-pilot-archive/op001/usability-findings.md](observe-pilot-archive/op001/usability-findings.md)
Finding 1.

### Step 2 — Pull one window of telemetry

Pick the **smallest meaningful window** — typically 1 hour of
CI/staging activity around a known recent failure. Smaller is
better. Larger windows do not teach you more about observation
quality; they just bury the signal.

Workflow varies by source — see
[INGESTION_GUIDE.md](INGESTION_GUIDE.md) for the recipes per source
(Jaeger, Loki, GHA artifact, S3, mixed directories). Each adapter
emits the same JSONL trace-bundle format that `arip observe`
consumes.

### Step 3 — Optional pre-pilot self-audit

Before running observe-mode against the full window, run the
existing `arip preflight` against a single representative failure
to confirm the engine can reason about your telemetry shape:

```bash
uv run arip preflight path/to/playwright-report.json
```

This produces the per-rule readiness checklist and quality score
without touching the observation store. If preflight reports
`low-confidence`, the observe-mode pilot will too — fix telemetry
first.

Or use the convenience wrapper:

```bash
bin/observe-self-audit.sh path/to/bundles.jsonl
```

It runs preflight semantics against the JSONL source by ingesting
the first 5 bundles into a throwaway store and printing the
per-band counts. Read-only outside the throwaway path.

### Step 4 — Observe

```bash
uv run arip observe path/to/bundles.jsonl \
    --store .arip/observation.db \
    --window 7d \
    --min-recurrence 1 \
    --digest-out reports/digest.md
```

Then **sit with the engineer** and let them read `reports/digest.md`.
Do not narrate it. Do not interpret it. Watch for:

- What is their first action? (Read the top section? Skip to a
  cluster? Ignore the abstentions? Close the doc?)
- Where do their eyes stop? (Recurrence column? Operations sample?
  Quality band?)
- What do they say out loud?
- What do they reach for next? (Jaeger to verify? Code to fix?
  Slack to escalate?)

### Step 5 — Capture

Copy `docs/observe-pilot-archive/_template/` to
`docs/observe-pilot-archive/<pilot-id>/`. Fill in the three short
templates (`operator-notes.md`, `usability-findings.md`,
`feedback.md`) immediately after the session. Memory decays in
minutes.

## What "success" looks like

A successful first observe-mode pilot is one where ALL of these hold:

- [x] Time-to-first-digest ≤ 30 minutes (target; ≤ 60 min hard ceiling)
- [x] Digest fits on one screen without scrolling for ≥ 70% of operators
- [x] Operator can articulate **one** anomaly pattern they did not
      previously know was recurring (or honestly confirm there are
      none, which is itself a useful signal)
- [x] Zero false-confident verdicts (engine produced no rule cluster
      that the engineer judged to be misleading)
- [x] "What this digest is NOT" disclaimer read; engineer did not
      mistake the digest for a list of bugs

If 4 of 5 hold, the pilot is a win and the trust contract held under
real telemetry. If ≤ 2 hold, file the friction as the headline
finding and stop — do not run a second pilot until the friction is
addressed.

## What "failure" looks like

A pilot fails (release-blocker class) if **any** of these is observed:

- The engine produces a high-confidence rule cluster that the
  engineer judges to be **wrong** — i.e. the cluster's claimed
  pattern is not what's actually happening
- The digest contains a confidently-worded sentence that overstates
  certainty (the hedging vocabulary is supposed to make this
  impossible; if it didn't, that's a P0 trust regression)
- The observation store is corrupted by a partial ingestion failure
  (we have tests against this; pilots are the second line)
- The adapter scripts produce output that silently changes between
  runs against the same input

Any of these earns a stop-the-line on observe-mode pilots until
fixed. File in `feedback.md` and link from the pilot index.

## What this pilot will NOT tell you

Be honest with the pilot participant about the boundary:

- It will not tell you whether ARIP can investigate a specific
  failing test — that's `arip investigate`'s job, validated in the
  investigation-mode pilot kit ([PILOT.md](../PILOT.md))
- It will not tell you whether ARIP can replace your APM dashboard
  — ARIP is not an APM (see [POSITIONING.md](POSITIONING.md))
- It will not tell you what the right thing to do about a recurring
  anomaly is — that's the engineer's job; the digest is one input
- It will not predict the next outage — observe-mode is descriptive,
  not predictive

If the engineer asks for any of the above, the honest answer is
"that's intentionally out of scope for Phase A."

## Operational artefacts for the pilot itself

- [observe-pilot-recruitment.md](observe-pilot-recruitment.md) —
  copy-paste-ready package for asking an engineer to pilot
- [OBSERVE_OPERATOR_BRIEFING.md](OBSERVE_OPERATOR_BRIEFING.md) — the
  5-min note the operator reads before the session
- [observe-pilot-candidates.md](observe-pilot-candidates.md) — OSS
  workloads suitable for a runner-self-pilot warm-up before the
  first real engineer pilot
- `bin/run-observe-pilot.sh` — the single command that scaffolds an
  archive directory, runs self-audit + observe, and hands off to
  the runner for verbatim capture

## Cross-references

- [OBSERVE_MODE.md](OBSERVE_MODE.md) — the technical reference
- [INGESTION_GUIDE.md](INGESTION_GUIDE.md) — per-source adapter
  recipes
- [observe-digest-examples.md](observe-digest-examples.md) —
  annotated good / noisy / empty / low-quality digest examples
- [observe-pilot-archive/](observe-pilot-archive/) — captured pilot
  artefacts
- [TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) — what to
  expect from real telemetry
- [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) — what's already
  been stress-tested under synthetic noise
- [FUTURE_ARCHITECTURE.md #11](FUTURE_ARCHITECTURE.md) — the
  capability that observe-mode is the first phase of (Phase B–D
  trigger conditions)
