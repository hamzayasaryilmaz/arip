# op001 — NO HUMAN OPERATOR (runner-self-pilot warm-up)

**This file does NOT contain operator feedback.** No human engineer
participated in this pilot. It was executed by the validation runner
against HotROD telemetry to exercise the unknown-system path of
observe-mode end-to-end before recruiting a real operator (op002).

Per [docs/observe-pilot-candidates.md](../../observe-pilot-candidates.md):

> "The warm-up pilot is explicitly labelled as such — its
> `feedback.md` records 'no real operator; runner-self-pilot to
> validate machinery only; do NOT count toward Phase 2 entry gate'.
> That's the honest discipline."

## Why this file exists at all

- To honour the archive structure (each pilot directory has feedback.md)
- To make the warm-up nature unmistakable to future readers
- To prevent this pilot's data being silently rolled into Phase 2
  entry-gate counts

## What IS in this archive

Factual artefacts only:

- `digest.md` — verbatim digest the engine produced
- `telemetry-summary.md` — factual ingestion + quality stats
- `self-audit.log` — pre-pilot smoke audit output
- `usability-findings.md` — RUNNER's observations about the
  observe-mode workflow (clearly attributed; not impersonating a
  human operator)
- `operator-notes.md` — same as this file: no human, no operator-side
  notes

## What the next archive (op002) MUST contain

The first real-operator pilot (`op002`) is for a recruited engineer
running observe-mode against their own CI/staging telemetry. That
pilot's `feedback.md` must:

- contain verbatim quotes from a real human
- record their trust assessment per cluster
- record their closing question answer

`op001` is not that pilot. It is the dry run for the runner.
