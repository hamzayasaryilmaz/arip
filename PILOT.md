# Pilot kit

**Mindset for this phase: build less, observe more.**

Everything below is about running ARIP against a real engineer's real
failure and learning what they actually think — not about adding
features. If the pilot exposes a gap, the *first* response is to
document it and decide whether it is in scope, not to write new code.

## Why pilots, not features

The MVP is done. The trust layer is in. The portability layer is in.
Five rules cover the five demo patterns plus their messy variants.
**Adding a sixth rule before a real engineer trusts the existing five
is wasted effort.** The remaining unknowns are operator-side, not
engine-side.

The strategic frame — what ARIP is, what it deliberately is NOT, and
where it fits relative to existing observability tools — lives in
[docs/POSITIONING.md](docs/POSITIONING.md). Pilots **inform** that
document; future features are **gated against** it.

What we want to learn:

- Does an engineer who has never seen ARIP open the report and find
  it useful?
- Do they read the *Alternative hypotheses* section, or only the
  *Primary*?
- When the engine abstains, do they trust the abstention or
  second-guess it?
- How much friction is the onboarding config?
- Where does the report mislead them, even subtly?

## Picking a pilot

A good first pilot has these traits:

| Trait                                 | Why it matters                                      |
|---------------------------------------|-----------------------------------------------------|
| Real production-style OTel telemetry   | We learn nothing from re-running the demo           |
| Playwright (or equivalent) test suite  | The collector layer is hardened against this        |
| Active CI with PRs                     | The sticky PR comment is half the value             |
| Engineer willing to give 30 minutes feedback | Telemetry of telemetry — without it the pilot is just deployment |
| Less than ~50 services                 | We're not solving multi-region telemetry routing yet |

Explicitly bad first pilots:

- "Let's run ARIP against our 200-service monolith from day one"
- A system where Playwright isn't the test runner
- A team that wants to evaluate ARIP without giving any feedback
- An environment that needs new telemetry infrastructure first

## Onboarding checklist

```
☐  1. Clone the ARIP repo at the pilot site
☐  2. Run `bin/arip-demo.sh` to confirm prerequisites
☐  3. Run `arip preflight` against a sample failing Playwright run
       from the pilot's CI (not from the demo)
☐  4. Read the preflight output — what does it say is missing?
☐  5. Edit configs/<pilot-name>.yaml to match local telemetry
       conventions (or accept defaults if OTel conventions are used)
☐  6. Re-run `arip preflight` — confirm rule readiness improved
☐  7. Wire up the GitHub Actions workflow (or equivalent)
☐  8. Open one real PR that surfaces an actual test failure
☐  9. Read the sticky comment
☐ 10. Capture the engineer's first reaction (verbatim) in
       docs/pilot-feedback-template.md
```

Target time: ≤ 90 minutes from clone to first sticky comment.

## What to capture from each pilot

We are not running anonymous A/B tests. We are running a small number
of qualitative sessions. For each session capture:

- **The failing trace** (anonymised). Stash anonymised spans + logs in
  `pilot-archive/<run-id>/` so the calibration benchmark can grow.
- **The generated report**. Both the markdown and the PR comment.
- **What the engineer did first**: Did they open the Jaeger trace?
  The alternatives section? The abstention diagnostics?
- **What they would have done WITHOUT ARIP** (their estimate).
- **Whether they trusted the primary hypothesis** (Y / partially / N).
- **One concrete suggestion** they wished ARIP did differently.

The template lives at
[docs/pilot-feedback-template.md](docs/pilot-feedback-template.md).

## Success criterion for this phase

The MVP's success criterion was: "Playwright fails → evidence-backed
report in < 60s." That has been met. The new criterion is:

> **A real engineer, in a real CI failure, opens ARIP's report and
> says "this was actually useful."**

That's a qualitative bar. Until at least three independent pilots
clear it, no new feature ships.

## Red lines

These will NOT change in response to pilot feedback. They are the
trust contract:

- The engine never produces a primary hypothesis when conflicting
  rules fire below the confidence ceiling. Pilots may dislike
  abstention; tough. We abstain.
- Evidence audit never relaxes. Every span_id / log line cited must
  exist in the live telemetry.
- The LLM never sees raw telemetry, only the deterministic finding.
- Severity / confidence numbers are never inflated to make the engine
  look more useful in screenshots.

If a pilot reports "the report would be more compelling if you just
showed confidence 0.95 everywhere", we say no. Trust is the moat.

## What can change in response to pilots

Almost everything else:

- Rule **descriptions** (wording, length, framing)
- The PR comment **layout**
- The order of sections in the markdown report
- The default `NormalizationConfig` values
- The set of signals tracked in quality assessment
- Onboarding documentation
- Examples and curated content

These are pure surface-area changes; no engine-reasoning impact. If a
pilot says "I had to scroll past 200 lines to find the trace link",
that's good feedback and the report layout shifts.

## Pilot deliverables (read these before opening a pilot)

| Deliverable                                          | Purpose                                          |
|------------------------------------------------------|--------------------------------------------------|
| [docs/POSITIONING.md](docs/POSITIONING.md)           | Strategic frame + the gate every roadmap change passes through |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md)                     | 7-minute walkthrough script for a live demo      |
| [QUICKSTART.md](QUICKSTART.md)                       | Clone-to-working-demo in 15 minutes               |
| [docs/ARIP_DEMO_WALKTHROUGH.md](docs/ARIP_DEMO_WALKTHROUGH.md) | Full self-paced walkthrough |
| [docs/ONBOARDING.md](docs/ONBOARDING.md)             | Per-rule contracts + signal coverage             |
| [docs/CALIBRATION.md](docs/CALIBRATION.md)           | Trust contract + benchmark scenarios             |
| [docs/abstention-gallery.md](docs/abstention-gallery.md) | "Why ARIP abstained" — curated cases        |
| [docs/calibration-gallery.md](docs/calibration-gallery.md) | Mixed-signal scenarios as readable narratives |
| [docs/before-after-investigation.md](docs/before-after-investigation.md) | The workflow comparison    |
| [docs/pilot-feedback-template.md](docs/pilot-feedback-template.md) | Per-session capture form |
| [docs/PILOT_RUNBOOK.md](docs/PILOT_RUNBOOK.md) | Step-by-step operational runbook (the *how*)      |
| [docs/PILOT_METRICS.md](docs/PILOT_METRICS.md) | Canonical trust-analytics definitions + thresholds |
| [docs/PILOT_SYNTHESIS_TEMPLATE.md](docs/PILOT_SYNTHESIS_TEMPLATE.md) | Cross-pilot synthesis (run every 3 pilots) |
| [docs/TELEMETRY_PATHOLOGIES.md](docs/TELEMETRY_PATHOLOGIES.md) | Live catalogue of real-world telemetry shapes      |
| [pilot-archive/](pilot-archive/) | Per-pilot artefact directory + `_template/`           |
| [docs/OBSERVE_PILOT_KIT.md](docs/OBSERVE_PILOT_KIT.md) | Parallel kit for observation-mode pilots (separate question, separate archive) |
| [docs/observe-pilot-archive/](docs/observe-pilot-archive/) | Per-observe-pilot artefact directory + `_template/` |

## Out of scope for pilots (do NOT promise these)

If a pilot asks for any of these, defer to roadmap, do not commit:

- SaaS / managed service
- Auto-remediation
- Time-travel / deterministic replay
- Multi-agent investigation
- Kubernetes operator
- AI-driven hypothesis generation
- Custom rules per tenant
- Real-time streaming investigation (post-failure only is the contract)

## What "done" looks like for this phase

A short list of artifacts:

1. ≥ 3 pilot sessions captured in `docs/pilot-feedback-template.md`
2. ≥ 1 anonymised real-world telemetry sample in `pilot-archive/`
3. A documented friction-point list, with each item triaged into
   "fix in next docs pass" or "out of scope, into FUTURE_ARCHITECTURE"
4. No engine-reasoning changes (this is the calibration discipline)

When this list is met, we have evidence the deterministic MVP can be
trusted by people who didn't build it. Only then do we revisit the
roadmap.
