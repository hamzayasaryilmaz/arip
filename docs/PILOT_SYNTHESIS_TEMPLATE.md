# Pilot synthesis template

Every 3 pilots, fill out a copy of this template at
`pilot-archive/_synthesis-<NNN>.md` (where `NNN` is the 3-pilot
window, e.g. `001` for the synthesis after the first three pilots).

This is where individual sessions stop being anecdotes and start
becoming evidence for what — if anything — should change.

## Purpose

The synthesis answers four questions:

1. **What recurring trust issues did we see?** (across pilots, not
   single sessions)
2. **What recurring friction blocked onboarding?**
3. **Which report sections did engineers value most? Ignore most?**
4. **What telemetry pathologies need to enter the calibration benchmark?**

If none of these questions has a clear answer yet, the synthesis is
"nothing recurring yet" — that is a valid outcome. Three pilots may
not be enough; do not invent patterns.

## Template

```markdown
# Pilot synthesis <NNN>

**Window:** pilots `<p###>`, `<p###>`, `<p###>`
**Synthesised by:** <name>
**Date:** <YYYY-MM-DD>

## Roll-up: trust metrics

| Metric                            | p###  | p###  | p###  | 3-pilot median | Threshold | Status |
|-----------------------------------|-------|-------|-------|-----------------|-----------|--------|
| false-high-confidence rate        |       |       |       |                 | < 5%      |        |
| abstention usefulness             |       |       |       |                 | ≥ 80%     |        |
| onboarding minutes                |       |       |       |                 | ≤ 30      |        |
| investigation time saved (×)      |       |       |       |                 | ≥ 5×       |        |
| report readability (1–5)          |       |       |       |                 | ≥ 4       |        |

(Status: ✅ pass / ⚠️ marginal / ❌ fail.)

## Recurring confusion

> Things that confused MORE THAN ONE engineer. If only one engineer
> was confused by something, it's noise; skip it.

Format:

| Pattern                                 | Pilots                | Triage decision                  |
|-----------------------------------------|-----------------------|-----------------------------------|
| <verbatim summary of confusion>         | p001, p003            | next docs pass / FUTURE_ARCH / fix |

## Repeated trust issues

> Cases where engineers verified ARIP's primary instead of trusting
> it. If this happens in 2+ pilots **for the same rule**, that rule
> needs investigation.

| Rule                | Pilots where verified-not-trusted | Root cause                  |
|---------------------|------------------------------------|-----------------------------|
|                     |                                    |                             |

## Onboarding blockers

> Specific points where setup got stuck in 2+ pilots.

| Blocker                                 | Pilots          | Fix surface       |
|-----------------------------------------|-----------------|-------------------|
| (e.g. "pilot's retry attribute doesn't match default") | p001, p002 | docs/ONBOARDING.md addition |

## Most-read sections (qualitative)

> Across pilots, which sections of the markdown report did the
> engineers consistently focus on?

| Section                  | Read in N of 3 pilots | Notes                        |
|--------------------------|------------------------|------------------------------|
| TL;DR                    |                        |                              |
| Primary hypothesis       |                        |                              |
| Evidence list            |                        |                              |
| Alternative hypotheses   |                        |                              |
| Request timeline         |                        |                              |
| Cross-run context        |                        |                              |
| Environment quality      |                        |                              |
| Failure metadata         |                        |                              |

## Least-read sections

> Sections that 2+ engineers explicitly skipped or said they didn't
> understand.

| Section                  | Why skipped              | Recommendation                |
|--------------------------|--------------------------|-------------------------------|
|                          |                          | compress / move / drop default |

## Telemetry pathologies catalogued

> Did any pilot's telemetry expose a real-world shape we hadn't
> seen? If so, this is the moment to add it to
> [TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) and — if
> appropriate — a corresponding synthetic-fixture test in
> `arip-core/tests/test_calibration_benchmark.py`.

| Pathology                                 | First seen | Catalogue entry | Calibration test? |
|-------------------------------------------|------------|-----------------|-------------------|
|                                           | p###       | (link)          | yes / no / later  |

**No new rule from a single pathology.** A new rule requires the
SAME pathology in ≥ 2 independent pilots AND a failed engineer-trust
moment that the existing rules cannot address.

## Decisions

For each finding above, exactly one of:

### Next docs pass

> Surface-area improvements — wording, layout, ordering. Cheap.
> Capture as issues, link here.

- [ ] (item) — issue link

### Out of scope → FUTURE_ARCHITECTURE.md

> Genuine new capability requests. Document with trigger condition.
> Do NOT build.

- [ ] (item) — FUTURE_ARCHITECTURE.md section

### Trust-layer regression (P0)

> Confidently-wrong RCAs that broke trust. Each is a release-blocker.
> Should be rare.

- [ ] (item) — P0 issue link

### Calibration benchmark addition

> A synthetic test that codifies a real-world pathology learned
> from these pilots.

- [ ] (item) — test name in `arip-core/tests/test_calibration_benchmark.py`

## Verdict

One sentence. Two options:

- **"Trust contract intact. Continue pilots."**
- **"Trust contract at risk on metric X. Pause new pilots until
  <named issue> is resolved."**

## Phase-2 readiness checklist (only fill once trust contract is intact)

- [ ] ≥ 3 independent pilots completed
- [ ] False-high-confidence rate < 5% in the 3-pilot window
- [ ] Median investigation time saved ≥ 5×
- [ ] At least one engineer said "I would actually use this on my team"
- [ ] No catastrophic trust failures (no `Trust-layer regression` entries)
- [ ] Onboarding median ≤ 30 minutes (or ≤ 90 with explanation)

If every box is checked, the gate to Phase 2 is unlocked. See
[ROADMAP.md → Phase 2 entry criteria](../ROADMAP.md#phase-2-entry-criteria).

If any box is unchecked, the gate stays closed. Run more pilots,
fix the failing metric, then re-synthesise.
```

## Synthesis discipline

- **Three pilots is the minimum window**, not the target. Five is
  better. Ten is great.
- The synthesis is **a reading of the archive**, not a re-running
  of the pilots. If the archive doesn't answer a question, the
  question stays open.
- Synthesis runs are committed to `pilot-archive/`, not edited
  after sign-off.
- A single dissenting voice does not move a recurring-pattern
  threshold. The bar is "≥ 2 pilots independently saw this."

## Failure mode: synthesis theatre

Resist filling in the template with content that "sounds right" if
the pilots didn't actually surface it. The right response to "we
have not seen recurring patterns yet" is **to write that down and
run more pilots**, not to extrapolate. Three pilots that all said
"the report was fine" is a stronger signal than three pilots
massaged into supporting a planned change.

If the synthesis pages start reading like roadmap proposals, that
is the signal that we have stopped observing and started building
again.
