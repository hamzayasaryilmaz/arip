# Pilot <ID> — <date> — <engineer initials>

> Copy this file from `pilot-archive/_template/feedback.md` to
> `pilot-archive/<pilot-id>/feedback.md` at the **start** of the
> session. Fill in during and immediately after the session.

> See `docs/pilot-feedback-template.md` for the canonical structure
> and how to fill each section. This file is the per-pilot instance
> of that template.

## Setup

- Pilot environment:        <one-line description>
- Telemetry stack:          <Jaeger / Tempo / OTel Collector / custom>
- Test framework:           <Playwright / Cypress / other>
- Time from clone to first
  sticky PR comment:        <minutes>
- ARIP config edits needed: <"none" / "N lines" / brief description>

## First impression (≤ 3 sentences)

> Verbatim engineer quote on first sight of the PR comment.

## What they did first

- [ ] Read the table at the top
- [ ] Opened the first `<details>` block
- [ ] Clicked a trace link
- [ ] Scrolled past it / ignored
- [ ] Other: <describe>

## Did they read alternatives?

- [ ] Read the primary only
- [ ] Read primary + scanned alternatives
- [ ] Read all candidates carefully
- [ ] N/A (engine abstained)

## Trust questions

- Did the engineer **trust the primary hypothesis**?
  - [ ] Yes, acted on it directly
  - [ ] Partially — verified against Jaeger first
  - [ ] No — formed their own hypothesis
  - [ ] N/A (engine abstained)

- Would the engineer have **arrived at the same conclusion unaided**?
  - [ ] Yes, but it would have taken much longer
  - [ ] Yes, in roughly the same time
  - [ ] Eventually, but might have gone in a different direction first
  - [ ] No — ARIP found something they would have missed

- Was the confidence number **interpretable**?
  - [ ] Yes
  - [ ] Sort of — they trust "high" but didn't read the 0.94
  - [ ] No, they ignored it

- For abstentions: did the abstention message **feel honest**?
  - [ ] Honest
  - [ ] Evasive
  - [ ] N/A

## Friction points

> One concrete paragraph.

## Misleading parts

> One concrete thing. "None" is valid.

## What they would change

> One concrete thing.

## Free-form notes

> Pilot-owner observations (not the engineer's words).

## Triage decision

- [ ] Next docs pass
- [ ] Out of scope → FUTURE_ARCHITECTURE.md
- [ ] Trust-layer regression — release-blocker
