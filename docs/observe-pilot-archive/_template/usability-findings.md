# Usability findings — `op<id>`

_Concrete issues with the observe-mode surface. One finding per
entry. Pair each observation with a proposed surface-level fix —
docs change, digest wording tweak, default flag adjustment. No
engine changes._

> If a finding really does require an engine change, write it down
> here AND escalate it as a P0 trust-regression in `feedback.md`.
> Mid-pilot engine changes are off-limits.

## Finding 1

- **Observation:** `<what the operator did or said that revealed
  a usability gap>`
- **Where in the digest / workflow:** `<specific section, column,
  CLI flag, or step in OBSERVE_PILOT_KIT.md>`
- **Severity:**
  - [ ] Critical — operator could not complete the workflow
  - [ ] Major — operator misinterpreted the output
  - [ ] Minor — operator was slowed down but recovered
  - [ ] Cosmetic — operator noticed but did not stumble
- **Proposed surface fix:** `<one-line change to docs / wording /
  defaults — NOT to engine behaviour>`
- **Routing:**
  - [ ] Next docs pass
  - [ ] OBSERVE_MODE.md update
  - [ ] INGESTION_GUIDE.md update
  - [ ] Digest template change (markdown-only — no scoring change)
  - [ ] Default flag change (e.g. `--min-recurrence` default)

## Finding 2

_(copy the structure above)_

## Findings that did NOT make the list

Things the operator complained about that look like
out-of-scope-for-Phase-A asks. Record verbatim for triage later, but
don't act on them in this pilot:

- "I wish it generated a test for me" → Phase C trigger, deferred
  to [FUTURE_ARCHITECTURE.md #11](../../FUTURE_ARCHITECTURE.md)
- "I wish it sent me a Slack alert" → out of scope, alerting is an
  anti-goal — see [POSITIONING.md](../../POSITIONING.md)
- "I wish it had a UI dashboard" → out of scope, dashboard is an
  anti-goal

Other:

- ...

## Summary

- Total findings: `<N>`
- Critical:   `<n>`
- Major:      `<n>`
- Minor:      `<n>`
- Cosmetic:   `<n>`

If `Critical + Major > 3`, the digest's first-pass usability is not
yet at pilot-ready quality. Stop and address before the next pilot.
