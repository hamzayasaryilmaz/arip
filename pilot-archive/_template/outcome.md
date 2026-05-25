# Outcome — <pilot-id>

> Filled in by the pilot owner within 48 hours of the session.

## Selection

- Why this pilot was chosen, against the criteria in
  `docs/PILOT_RUNBOOK.md` Step 1:
- Any waived disqualifiers (rare, justify):

## Onboarding timeline

| Phase                              | Minutes |
|------------------------------------|---------|
| git clone → `bin/arip-demo.sh`     |         |
| First preflight pass               |         |
| Config edits                       |         |
| GitHub Actions wired               |         |
| First failing PR opened            |         |
| First sticky comment posted        |         |
| **Total clone → first comment**    |         |

Threshold: **30 minutes** for a clean OTel environment, **90
minutes** upper bound. Anything past this goes in friction points.

## Friction points (verbatim)

> Each as a single-paragraph quote from the pilot engineer or
> verbatim observation from the pilot owner.

## Trust verdict (from feedback.md)

| Question                                                            | Answer                          |
|---------------------------------------------------------------------|---------------------------------|
| Did they trust the primary hypothesis?                              | Yes / Partial / No / Abstain    |
| Would they have arrived at the same conclusion unaided?             | Yes-faster / Yes-same / Eventually / No |
| Did the report mislead them, even slightly?                         | Yes (concrete example) / No     |
| Would they recommend ARIP to a teammate?                            | Yes / Maybe / No                |

## Metrics (computed per docs/PILOT_METRICS.md)

| Metric                                | Value | Threshold | Pass? |
|---------------------------------------|-------|-----------|-------|
| false-high-confidence rate            |       | < 5%      |       |
| abstention usefulness                 |       | ≥ 80%     |       |
| onboarding friction (minutes)         |       | ≤ 30      |       |
| investigation time saved (×, median)  |       | ≥ 5×       |       |
| evidence clickthrough (which links?)  |       | (qualitative) |   |
| report readability (1–5)              |       | ≥ 4       |       |
| alternative-hypothesis usefulness     |       | (qualitative) |   |

## Pathologies observed

> Cross-reference docs/TELEMETRY_PATHOLOGIES.md by category.
> If a NEW pathology was seen, add an entry there and link from here.

## Decisions

### Triaged into next docs pass

- (item) — links to issue / PR

### Out of scope → FUTURE_ARCHITECTURE.md

- (item) — with trigger condition

### Trust-layer regression (rare; release-blocker)

- (item) — links to P0 issue

## Sign-off

- **Pilot owner:**                <name>
- **Anonymisation reviewer:**     <name> (must be a different person)
- **Date:**                       <YYYY-MM-DD>

This document is frozen after sign-off. To revise it, open a new
pilot, not a re-edit.
