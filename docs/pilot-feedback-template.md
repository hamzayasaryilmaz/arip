# Pilot feedback template

Copy this template to `pilot-archive/<pilot-id>/feedback.md` at the
end of each pilot session. Keep it short. Long forms produce
performative answers; short forms produce honest ones.

If a section has no honest answer, write *"not applicable"* or
*"didn't try"*. Do **not** invent answers.

---

```markdown
# Pilot <ID> — <date> — <engineer initials>

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

When the PR comment appeared, what was their FIRST action?

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

For the primary hypothesis (or the abstention):

- Did the engineer **trust the primary**?
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

- For abstentions: did the abstention message **feel honest** or
  **feel evasive**?
  - [ ] Honest — they read why and accepted it
  - [ ] Evasive — they wanted a primary even though signal was thin
  - [ ] N/A (no abstention this run)

## Friction points

The biggest single friction during setup or use:

> One concrete thing, one paragraph.

## Misleading parts

Anything in the report that subtly misled them, even if minor:

> One concrete thing. "None" is a valid answer.

## What they would change

If they could change ONE thing about the report or workflow:

> One concrete thing.

## Free-form notes

Anything else the pilot runner observed (not the engineer's words):

> Notes on body language, hesitation, double-takes, etc.

## Decision

- [ ] Feedback goes into "next docs pass" — surface-area improvement
- [ ] Feedback goes into FUTURE_ARCHITECTURE — out-of-scope but logged
- [ ] Feedback indicates a trust-layer regression — needs immediate fix

(Most feedback is the first bucket. The third should be rare; if it
happens, treat as a release blocker.)
```

---

## How to use the captured feedback

After each pilot:

1. Save the filled template at `pilot-archive/<pilot-id>/feedback.md`.
2. Save the anonymised telemetry (spans + logs) at
   `pilot-archive/<pilot-id>/{spans,logs}.json`.
3. If the case is novel and would expand the calibration benchmark,
   also write `pilot-archive/<pilot-id>/expected_behavior.md`.
4. After every 3 pilots, do a triage pass: which friction points
   group together? Update docs accordingly.

The goal is NOT to act on every individual data point. The goal is
to see patterns across pilots, then make small surface-area
improvements that resolve those patterns.

## What this is not

This template is deliberately **not**:

- An NPS score
- A feature-request form
- A defect tracker (use issues for those)

It is a small qualitative instrument for capturing whether ARIP, as
shipped, gives a real engineer something they trust.
