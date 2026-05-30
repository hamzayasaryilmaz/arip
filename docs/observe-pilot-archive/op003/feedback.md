# op003 — NO HUMAN OPERATOR (runner-self-pilot warm-up)

**This file does NOT contain operator feedback.** No human engineer
participated in this pilot. It was executed by the validation runner
against **Grafana Tempo (single-binary)** telemetry to exercise the unknown-system path of
observe-mode end-to-end as part of the multi-system unknown-systems
validation pass.

See [docs/UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
for the cross-system synthesis. This archive is one data point in that
synthesis.

Per [docs/observe-pilot-candidates.md](../../observe-pilot-candidates.md):

> *"The warm-up pilot is explicitly labelled as such — its
> `feedback.md` records 'no real operator; runner-self-pilot to
> validate machinery only; do NOT count toward Phase 2 entry gate'.
> That's the honest discipline."*

## What this archive contains

Factual artefacts only:

- `digest.md` — verbatim digest the engine produced (post-fix where applicable)
- `telemetry-summary.md` — factual ingestion + quality stats
- `self-audit.log` — pre-pilot smoke audit output
- `usability-findings.md` — RUNNER's observations about the
  observe-mode workflow on this specific system
- `operator-notes.md` — same as this file: no human, no operator-side notes

## Does NOT count toward Phase 2 entry gate

`op001`, `op002`, and `op003` are all runner-self-pilots against
unknown OSS systems. The Phase 2 entry-gate quorum (≥ 3 independent
pilots clearing the gate) requires REAL engineers running observe-mode
against THEIR OWN telemetry — that's `op004` and beyond.

The runner-self-pilots validate that:

1. The pilot machinery works end-to-end on unknown systems
2. The trust contract holds under genuinely-novel telemetry
3. Real defects in the engine surface during validation, not via users

They do NOT validate that real engineers find the digest useful.
That is a separate, higher bar.
