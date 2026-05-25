# Observation mode (Phase A)

This document describes `arip observe`: ARIP's continuous,
**observation-only** capability. It exists to answer one question:

> *Which anomaly patterns are actually recurring against this telemetry?*

It does NOT generate candidate tests, open PRs, run replay, page
anyone, or take any other action. Observation mode is a read-only
layer over the same deterministic engine that powers `arip
investigate`.

If you are looking for the broader QA/regression-assistance roadmap
this capability is the first phase of, see
[FUTURE_ARCHITECTURE.md item #11](FUTURE_ARCHITECTURE.md).

If you are about to run the first real pilot, start with
[OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md) and skim
[observe-digest-examples.md](observe-digest-examples.md) to
calibrate expectations before opening the first digest.

## What it is

`arip observe` reads a stream of trace bundles, runs each through the
existing 5-rule engine, and records the engine's verdict — either a
rule-grounded hypothesis or an abstention — into a local SQLite store.
Identical-shape observations collapse onto a single cluster whose
`recurrence_count` you can see in the digest.

That is the whole capability for Phase A.

## What it is not

- Not a telemetry collector — sources are pull-based; nothing is sent
  to ARIP. ARIP polls.
- Not a storage backend — state is local SQLite; events are pruneable.
- Not an alerting tool — `recurrence_count` is descriptive, not a
  threshold for paging.
- Not a candidate-test generator — no tests are drafted, no PRs are
  opened. Phase A is intentionally silent on those.
- Not a parallel reasoning system — observation runs the same
  `engine.investigate(...)` path as `arip investigate`. There is one
  engine; observation mode just gives it production-style telemetry.

## Quick start

```bash
# One-shot
uv run arip observe path/to/traces.jsonl

# With a custom store and a digest window
uv run arip observe path/to/traces.jsonl \
  --store .arip/observation.db \
  --window 7d

# Replay digest only (no new ingestion)
uv run arip observe path/to/traces.jsonl --no-ingest
```

Sources accepted:

- `path/file.jsonl` — JSONL trace bundles, one per line (auto-detected)
- `path/file.jsonl.gz` — gzipped JSONL, transparent decompression
- `path/dir/` — directory of `*.json` bundles (one per file)
- `jsonl://path` and `dir://path` — explicit URI forms

## Trace-bundle JSON shape

A bundle is a single trace plus its correlated logs. One JSON object
per JSONL line, or one JSON file per directory entry:

```json
{
  "trace_id": "abc...",
  "captured_at": "2026-05-20T10:23:00Z",
  "spans": [
    {
      "trace_id": "abc...",
      "span_id": "s1",
      "parent_span_id": null,
      "service_name": "payment-service",
      "operation_name": "POST /checkout",
      "start_time": "2026-05-20T10:23:00.001Z",
      "duration_us": 12000,
      "status": "ERROR",
      "status_message": "",
      "attributes": {"http.status_code": 500},
      "events": []
    }
  ],
  "logs": [
    {
      "timestamp": "2026-05-20T10:23:00.005Z",
      "service_name": "payment-service",
      "level": "ERROR",
      "message": "...",
      "trace_id": "abc...",
      "fields": {}
    }
  ]
}
```

Spans and logs use the same shape `arip investigate` already accepts —
this is the same data flowing through a different entry point.

## Cursors and resumability

Each source maintains its own cursor (one row in
`obs_cursors` keyed by source URI). Cursors persist after every
processed observation, not just at end-of-run. A crash mid-stream
resumes on the next line, not at the start.

- JSONL cursor → byte offset of next line
- Directory cursor → most recently emitted relative filename

To re-process a source from scratch, delete its cursor row or use a
new store path.

## Bounded by design

| Constraint | Mechanism |
|---|---|
| Memory bounded | Sources are generators; pipeline is one-observation-at-a-time |
| CPU bounded | `--budget` (default 500 observations per run) |
| Storage bounded | `prune_events_older_than(retention_days)` (events; clusters persist) |
| Recurrence bounded | Idempotent on `(source, observation_id)` — replays don't double-count |
| Side-effect bounded | No mutation of sources; no network egress; no PR/alert |

## How clustering works

Every processed observation gets one fingerprint:

- **Rule-grounded** — the engine produced a primary hypothesis. The
  fingerprint is `fingerprint_hypothesis(primary)` — same algorithm
  used by cross-run memory in `arip investigate`. A production-observed
  `retry_storm` shares a fingerprint with a CI-investigated one.
- **Abstention-grounded** — the engine declined. The fingerprint
  folds the abstention code with the service set and a truncated
  operation-name sample. This lets recurring telemetry pathologies
  (e.g. `weak_evidence` repeating on `POST /checkout`) surface as
  patterns even though no hypothesis was produced.

Observations with no clusterable result (engine produced neither a
primary nor an abstention — should not happen by construction) are
silently dropped. That is the only silent drop; everything else is
recorded.

## Reading the digest

The digest has three substantive sections + an honesty section:

1. **Run summary** (this run's ingestion)
2. **Recurring patterns (rule-grounded)** — engine produced a primary
3. **Recurring abstentions** — engine declined; useful for telemetry
   hygiene, not for acting on the anomaly itself
4. **What this digest is NOT** — the honesty disclaimer is part of
   every digest, intentionally

A rule-grounded cluster is *not* a verdict. It is a recurring
evidence-aligned observation. The same trust contract that governs
`arip investigate` reports governs these clusters: every backing
event passed evidence audit, every abstention code is one of the
five canonical codes.

## Quality band propagation

The same quality assessor that runs in investigation mode runs in
observation mode. Each event records the `quality_band` (high /
medium / low) and the cluster reports the dominant band. Low-quality
observations are counted separately and surfaced as a single number,
not folded into rule clusters — they exist for transparency without
inflating recurrence figures.

## Production safety

`arip observe` is read-only by contract. It does not:

- mutate source files (verified by a test)
- emit network traffic to the source's backing infra (sources read
  local files in Phase A)
- replay any production request
- write to the memory store used by `arip investigate`
- open PRs, send notifications, or call external APIs

It can be run on a developer laptop against a directory of archived
trace bundles. It does not need any production access beyond a file
copy.

## Retention

The observation store has two retention surfaces:

- Per-event rows: prune via `store.prune_events_older_than(N_days)`
- Per-cluster rows: persist across pruning (aggregates only)

There is no automatic pruning in Phase A; the operator schedules it.
This is deliberate — automatic data deletion in a state file the
operator may not yet trust is a worse default than slight bloat.

## When ARIP observation will NOT help

- Source telemetry has no `trace_id` correlation across services →
  every trace looks like a single-service blip; clustering becomes
  shallow. Fix the upstream telemetry first.
- All observations land in `low` quality band → the engine cannot
  reason about them; clusters will be abstention-only. Same fix.
- The recurring failure mode is not covered by any of the 5 rules →
  observation mode honestly reports `no_rule_matched` abstentions
  rather than guessing. That is the design.

## What this enables next (and what blocks it)

Phase A is the **observation-only** entry point of the longer
QA/regression-assistance roadmap in
[FUTURE_ARCHITECTURE.md item #11](FUTURE_ARCHITECTURE.md). The next
phases (B narrative, C candidate generation, D sandbox) do not begin
until:

1. The Phase 2 entry gate in [ROADMAP.md](../ROADMAP.md) clears
   (≥ 3 pilots; false-high-confidence < 5%), AND
2. ≥ 3 pilot post-mortems verbatim state Phase B (cluster narrative)
   would meaningfully accelerate their regression authoring.

Until both hold, observation mode stays observation-only. That is the
design — observation is cheap, candidate generation is not, and the
moat lives in trust discipline, not in surface area.
