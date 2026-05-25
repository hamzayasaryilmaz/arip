# Pilot metrics

Canonical trust-analytics definitions. Every pilot's `outcome.md`
populates the same numbers using the formulas here, so trust signals
are comparable across pilots.

These are **the only metrics that gate Phase 2 entry.** Anything else
captured during a pilot is qualitative context, useful for synthesis
but not for the gate.

## 1 · False-high-confidence rate

> **The single most important metric.** If it exceeds 5% across any
> three consecutive pilots, the trust contract has cracked. Pause
> new pilots and investigate as a release-blocker.

**Definition:** the fraction of investigations where the engine
produced a *primary hypothesis* (not an abstention) whose primary
finding was **wrong** in the pilot engineer's judgement, **and** the
confidence on that primary was ≥ 0.85.

**Why ≥ 0.85:** the conflict-detection ceiling. Above this, the engine
is signalling "I am confident enough to commit." Wrong commits at
this level are the failure mode that destroys trust.

**Computation per pilot:**

```
false_high_confidence_rate
   = (# primaries at conf ≥ 0.85 marked wrong by engineer)
   / (# primaries at conf ≥ 0.85)
```

Per pilot is fine when N is small (usually 1 primary). The
release-blocker rule operates on **rolling 3-pilot windows**: never
> 5% in any window.

**Captured in:**
- `outcome.md` → Metrics table → `false-high-confidence rate`
- `feedback.md` → "Did the engineer trust the primary hypothesis?"

**Threshold:** **< 5%** across any rolling 3-pilot window.

## 2 · Abstention usefulness

**Definition:** when the engine abstained instead of nominating a
primary, did the pilot engineer agree the failure WAS ambiguous
enough to deserve an abstention?

If they agreed → useful abstention. If they thought the engine
"chickened out" and the right finding was obvious → unhelpful
abstention.

**Computation:**

```
abstention_usefulness
   = (# abstentions the engineer marked "honest")
   / (# abstentions total)
```

**Captured in:**
- `feedback.md` → "For abstentions: did the abstention message feel
  honest or evasive?"

**Threshold:** **≥ 80%** of abstentions felt honest. Below this,
the abstention thresholds are too conservative (engine is hiding
findings it could nominate).

## 3 · Evidence clickthrough

**Definition:** *where the engineer's attention went* — qualitative,
not numeric. Did they click any trace link in the report? Did they
read the evidence list, or only the headline?

**Computation:** observation-based. Pilot owner records during the
session:

- First click target (Jaeger trace link / report file / details block)
- Whether they read the per-attempt evidence rows
- Whether they consulted the timeline section

**Captured in:**
- `feedback.md` → "What they did first"
- `outcome.md` → Metrics table → free-text

**No threshold.** This is for synthesis — if 3+ pilots ignore the
"Request timeline" section, that's a layout signal.

## 4 · Onboarding friction

**Definition:** wall-clock minutes from `git clone` to first sticky
PR comment on a real failing PR.

**Computation:** timestamped by the pilot owner during Step 3 of
the runbook.

**Captured in:**
- `outcome.md` → Onboarding timeline table

**Thresholds:**
- **≤ 30 min** — clean OTel-conforming environment (target)
- **≤ 90 min** — acceptable upper bound
- **> 90 min** — escalates as a friction point automatically

## 5 · Investigation time saved

**Definition:** the engineer's *self-reported* estimate of how much
time they would have spent investigating the same failure without
ARIP, divided by how long the ARIP-assisted flow actually took.

**Computation:**

```
investigation_time_saved
   = (engineer's estimate of manual investigation time)
   / (actual ARIP-assisted minutes)
```

So `5×` means "would have taken 25 minutes manually, took 5 with
ARIP."

**Captured in:**
- `outcome.md` → Metrics table
- `feedback.md` → "Would they have arrived at the same conclusion
  unaided?" (qualitative anchor)

**Threshold:** **≥ 5× median across pilots**. Below this, the
PR-comment workflow isn't earning its keep — engineers could just
read the Playwright failure and click into Jaeger.

This is self-reported and therefore noisy. Use the median across
pilots, never a single number.

## 6 · Report readability

**Definition:** 1–5 Likert from the pilot engineer at the end of
the session: "How easy was the report to read end-to-end?"

**Computation:** numeric mean across pilots.

**Captured in:**
- `outcome.md` → Metrics table

**Threshold:** **mean ≥ 4** across the first three pilots. If lower,
the layout needs polish — high-leverage docs work, not engine work.

## 7 · Alternative-hypothesis usefulness

**Definition:** when the engine surfaced one or more **alternative**
hypotheses below the primary, did the pilot engineer find any of
them useful (read them, weighted them, or acted on them)?

**Computation:** observation + post-session question.

- "Did you read the alternatives section?"
- "Was any alternative more useful to you than the primary?"
- "Would you have wanted MORE alternatives, or fewer?"

**Captured in:**
- `feedback.md` → "Did they read alternatives?"
- `outcome.md` → Metrics table → free-text

**No fixed threshold.** This is a layout-and-pacing signal:
- ≥ 50% read alternatives → the section earns its space.
- < 50% → consider compressing or hiding-by-default.

## How metrics roll up

After every 3 pilots, run the synthesis exercise in
[PILOT_SYNTHESIS_TEMPLATE.md](PILOT_SYNTHESIS_TEMPLATE.md). The
rolled-up metrics gate the Phase 2 transition in
[ROADMAP.md → Phase 2 entry criteria](../ROADMAP.md#phase-2-entry-criteria).

## Anti-patterns

- **Don't aggregate before 3 pilots.** Single-pilot numbers are
  anecdote. Three is the smallest useful window.
- **Don't smooth.** Report the actual values; if false-high-confidence
  hits 6% on one pilot, that's a P0 investigation, not a noise
  threshold to dismiss.
- **Don't redefine.** If a metric proves the wrong thing, write a
  new metric, don't redefine an existing one.
- **Don't add metrics mid-pilot.** Capture extra context as
  qualitative notes; new metrics start counting from the next pilot.
