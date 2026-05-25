# docs/observe-pilot-archive/

Per-pilot archives for **observation-mode** sessions. Mirrors the
shape of [`pilot-archive/`](../../pilot-archive/) at the repo root,
which holds investigation-mode pilots — kept separate because the
two pilot kits ask different questions and capture different
artefacts.

These directories are **committed to the repo, not gitignored.**
Together with the investigation-mode archive, they form the trust
calibration corpus for Phase A.

## Directory shape

```
docs/observe-pilot-archive/
├── README.md                  ← you are here
├── _template/                 ← copy this when starting a new pilot
│   ├── operator-notes.md
│   ├── usability-findings.md
│   ├── feedback.md
│   ├── digest.md              ← captured verbatim from the run
│   └── telemetry-summary.md   ← what was ingested + quality snapshot
└── <pilot-id>/                ← one directory per pilot, e.g. op001/, op002/
    └── ... same 5 files
```

## What goes into each file

| File | Purpose |
|---|---|
| `operator-notes.md` | What the pilot runner observed about the operator's behaviour while reading the digest. Body language, click order, surprised reactions. Not the operator's own words. |
| `usability-findings.md` | Concrete usability issues — verbose sections, confusing columns, missing context. Each entry pairs an observation with a one-line proposed fix. |
| `feedback.md` | The operator's verbatim words. Direct quotes only. |
| `digest.md` | The full markdown digest the operator saw, captured unchanged so future readers can see what the operator was reacting to. |
| `telemetry-summary.md` | Source description, time window, traces ingested, quality band distribution, abstention code counts. No PII. |

## Pilot ID convention

- `op001`, `op002`, `op003` … (zero-padded, three digits)
- The `op` prefix distinguishes observe-mode pilots from `p001` /
  `p002` investigation-mode pilots in `pilot-archive/`

## How to run a pilot

Use the single-command runner:

```
./bin/run-observe-pilot.sh <source> opNNN
```

It scaffolds this directory from `_template/`, runs self-audit +
observe, writes `digest.md`, and prints the "Run summary" block to
paste into `telemetry-summary.md`. Re-running on the same pilot-id
preserves any feedback already filled in.

See [docs/OBSERVE_PILOT_KIT.md](../OBSERVE_PILOT_KIT.md) for the
runner's full workflow,
[docs/observe-pilot-recruitment.md](../observe-pilot-recruitment.md)
for the package to send to candidate engineers, and
[docs/observe-pilot-candidates.md](../observe-pilot-candidates.md)
for OSS workloads to warm up against before recruiting.

## When to file a pilot

Immediately after the session. Memory of the operator's reactions
decays in minutes; "let's write it up tomorrow" produces sanitised
narratives, not honest captures. The five templates are short on
purpose so the cost of filing is low.

## What NOT to commit

- Any raw PII or customer-identifying data from the telemetry
- Any internal hostnames, account IDs, full request bodies
- The operator's name unless they explicitly approved
- Slack screenshots of the conversation

The `digest.md` you capture is already PII-light by construction
(operation names, service names, recurrence counts) — but verify
before committing. If anything is borderline, scrub it.

## Reading the corpus

After the first 3 observe-mode pilots are filed, the right next
move is a synthesis pass — the same shape as
[`PILOT_SYNTHESIS_TEMPLATE.md`](../PILOT_SYNTHESIS_TEMPLATE.md) but
focused on observe-mode-specific findings. Defer until 3 are filed;
synthesising one or two pilots is pattern-matching on noise.
