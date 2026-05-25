# Pilot runbook

How to execute a single pilot session from selection to archive.
Deterministic, repeatable. If a step here is skipped, the pilot's
data is not comparable to others and should not feed
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) or
[PILOT_SYNTHESIS_TEMPLATE.md](PILOT_SYNTHESIS_TEMPLATE.md).

Read [PILOT.md](../PILOT.md) for the *why*. This doc is the *how*.

## Mode reminder

**Default operating mode is now `observe`, not `build`.** During a
pilot:

- Do not add a new rule, even if the pilot's failure exposes a gap.
- Do not add a new scenario.
- Do not add a new architecture layer.
- Do not "fix" telemetry to make ARIP look better.
- Do not extend the report wording mid-pilot to make a finding clearer.

All of those exist in
[PILOT.md → What can change in response to pilots](../PILOT.md#what-can-change-in-response-to-pilots);
mid-pilot mutation invalidates the data.

The freeze list is enforced in [ROADMAP.md → Phase 2 entry criteria](../ROADMAP.md#phase-2-entry-criteria).

## Pre-pilot — done once, before any session

| Step                                                                                 | Owner   |
|--------------------------------------------------------------------------------------|---------|
| Confirm POSITIONING.md and PILOT.md are committed to main, links resolve             | ARIP    |
| Confirm `bin/arip-demo.sh` and `bin/arip-demo-recording.sh` run cleanly on a fresh clone | ARIP    |
| Confirm 109/109 tests green and calibration benchmark is stable                      | ARIP    |
| Allocate a `pilot-archive/` directory for the upcoming session                       | ARIP    |
| Pick a pilot ID — short, anonymous, e.g. `p001`                                      | ARIP    |

## Step 1 — Pilot selection

A candidate must clear all of these. If they miss one, defer.

- [ ] OpenTelemetry instrumentation in production (any flavour)
- [ ] Playwright (or Cypress) in CI
- [ ] GitHub Actions or GitLab CI
- [ ] 50–300 engineers
- [ ] Test flakiness or distributed-failure debugging is a known team pain point
- [ ] Engineer willing to give ≥ 30 minutes of feedback after the session
- [ ] Engineer is *not* a member of the ARIP team

**Anti-selection** (any one disqualifies):
- [ ] No OTel
- [ ] No Playwright / Cypress
- [ ] Pre-product startup (CI not mature)
- [ ] 1000+ engineer enterprise (procurement bottleneck)
- [ ] Pilot expects ARIP to replace Datadog/Honeycomb
- [ ] Pilot expects SaaS / hosted ARIP

Capture selection in `pilot-archive/<pilot-id>/outcome.md`'s
`## Selection` section. If something was waived, write **why**.

## Step 2 — Telemetry readiness check

Before running ARIP, take a 5-minute sample of the pilot's telemetry
to a JSON dump and run a local quality assessment.

```bash
# Capture one failing Playwright run from the pilot's CI:
# - playwright-report.json
# - One representative trace JSON from Jaeger/Tempo
# - A snippet of the relevant service logs

# Run preflight against this sample:
uv run arip preflight <playwright-report.json> --config configs/<pilot-id>.yaml
```

Capture the preflight output verbatim into
`pilot-archive/<pilot-id>/telemetry-quality.json` (the `arip
investigate` command already produces the structured assessment in
the report's JSON twin — extract the `quality` field).

If the preflight reports a `low`-confidence environment with > 2
critical findings, **do not proceed** until the pilot fixes the
telemetry gaps. Running ARIP on broken telemetry teaches us about
ARIP's failure modes, not about engineer trust — different question.

## Step 3 — Onboarding flow (target: ≤ 90 minutes from clone to first PR comment)

The pilot owner (you) drives the keyboard; the pilot engineer
watches and asks questions. Do NOT silently work around their
environment quirks — record them as friction points.

Onboarding checklist (copy into `pilot-archive/<pilot-id>/outcome.md`):

```
☐  1. git clone <ARIP-repo>
☐  2. bin/arip-demo.sh — confirm prerequisites
☐  3. arip preflight <pilot's playwright-report.json>
☐  4. Edit configs/<pilot-id>.yaml — only fields whose names differ
☐  5. arip preflight again — confirm rule readiness improved
☐  6. Wire up .github/workflows/arip-investigate.yml in pilot's repo
☐  7. Open one real PR that surfaces a real failure
☐  8. Read the sticky comment together
☐  9. Engineer's first reaction captured verbatim
☐ 10. Time-stamp everything
```

Time the onboarding. The threshold is **30 minutes** for a clean
OTel environment; **90 minutes** is the upper bound where the pilot
is still considered "frictionless". Anything beyond 90 minutes goes
straight into `friction-points` in the outcome.

## Step 4 — Config setup

Always start from `configs/demo.yaml` as a template:

```bash
cp arip-core/configs/demo.yaml pilot-archive/<pilot-id>/config.yaml
```

Edit only fields whose names differ from defaults. If the pilot uses
OTel semantic conventions out of the box, most fields require no
change. Common edits seen in early pilots will populate
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) over time.

Capture every edit with the reason inline:

```yaml
business_keys:
  - account_id      # pilot uses account_id, not order.id
  - subscription_id # multi-product accounts also tagged here
```

Commit the final config as
`pilot-archive/<pilot-id>/config.yaml`.

## Step 5 — First failing PR

The pilot engineer opens a PR that exercises a real test failure
(not a synthesised one). They do **not** show ARIP the report
beforehand — let them open the PR comment fresh.

The pilot owner observes:

- Where do their eyes go first on the comment?
- What do they click first?
- Do they read the alternatives section?
- Do they trust the primary, or verify in Jaeger?

Record observations verbatim in `feedback.md` under
`## What they did first`.

Save the report and PR comment:

```bash
cp reports/<failing-test>-*.md  pilot-archive/<pilot-id>/generated-report.md
cp arip-pr-comment.md           pilot-archive/<pilot-id>/pr-comment.md
```

## Step 6 — Feedback collection

After the engineer has read the report, walk them through
[docs/pilot-feedback-template.md](pilot-feedback-template.md)
section by section. Capture verbatim where possible.

Save as `pilot-archive/<pilot-id>/feedback.md`.

**The three required questions** (the gate for this whole pilot):

1. Did the engineer trust the primary hypothesis?
   (Yes / Partially / No / N/A-abstain)
2. Would the engineer have arrived at the same conclusion unaided?
   (Yes-faster / Yes-same-time / Eventually / No)
3. Did the report mislead them, even slightly?
   (Concrete example; "no" is a valid answer)

These three answers are the engineer-trust signal. Everything else is
secondary.

## Step 7 — Telemetry anonymisation

Real telemetry contains business data (user IDs, order IDs, account
names). Strip it before archiving:

```bash
# From the pilot's Jaeger:
curl 'http://<pilot-jaeger>/api/traces/<failing-trace-id>' \
  | python3 arip-core/scripts/anonymise_trace.py \
  > pilot-archive/<pilot-id>/spans.json

# From the pilot's logs:
docker logs <pilot-service> --since=<failure-time> \
  | python3 arip-core/scripts/anonymise_logs.py \
  > pilot-archive/<pilot-id>/logs.json
```

(Anonymise scripts are placeholder — first pilot writes them as part
of the run. Strip emails, account IDs, tenant names, hostnames; keep
trace_ids, span_ids, operation_names, durations, status codes.)

**Anonymisation rules:**
- Replace business identifiers with `<entity-N>` placeholders, where
  the same identifier always maps to the same placeholder (consistent
  re-mapping).
- Keep trace structure verbatim. Do not alter parent-child links,
  timings, or attribute *names*.
- Strip PII: emails, IPs, real domain names.
- Sign off the anonymisation in `outcome.md` — name of the person
  who reviewed it.

## Step 8 — Archive

Final structure of `pilot-archive/<pilot-id>/`:

```
pilot-archive/<pilot-id>/
├── feedback.md              ← filled-in pilot-feedback-template.md
├── outcome.md               ← post-pilot review (Step 10)
├── config.yaml              ← normalization config used
├── telemetry-quality.json   ← preflight + investigation quality data
├── generated-report.md      ← the report ARIP produced
├── pr-comment.md            ← the PR comment ARIP rendered
├── spans.json               ← anonymised trace
└── logs.json                ← anonymised logs
```

All files are committed to the repo. No `.gitignore` exclusions for
`pilot-archive/`.

## Step 9 — Trust analytics

For every pilot, populate `telemetry-quality.json` and compute the
canonical metrics defined in
[docs/PILOT_METRICS.md](PILOT_METRICS.md):

- false-high-confidence rate (this run)
- abstention usefulness (if engine abstained)
- evidence clickthrough (where did the engineer's eye go?)
- onboarding friction (minutes from clone to first useful comment)
- investigation time saved (their estimate, post-session)

These numbers go in `outcome.md`.

## Step 10 — Post-pilot review

Within 48 hours of the session, the pilot owner writes
`pilot-archive/<pilot-id>/outcome.md` with:

```markdown
# Outcome — <pilot-id>

## Selection
- Why this pilot was chosen, against the criteria in Step 1
- Any waived disqualifiers

## Onboarding timeline
- Clone → first PR comment: X minutes
- Friction points (verbatim)

## Trust verdict (from feedback.md)
- Did they trust the primary hypothesis?
- Did the report mislead them?
- Would they recommend ARIP to a teammate?

## Metrics
| Metric                          | Value |
|---------------------------------|-------|
| false-high-confidence rate      | …     |
| abstention usefulness           | …     |
| onboarding minutes              | …     |
| investigation time saved        | …     |

## Pathologies observed
- Any telemetry pathologies (cross-ref TELEMETRY_PATHOLOGIES.md)

## Decisions
- "Triaged into next docs pass" — list, link to issues
- "Out of scope, into FUTURE_ARCHITECTURE.md" — list, link
- "Trust-layer regression — needs fix" — list (should be rare)

## Sign-off
- Pilot owner: <name>
- Anonymisation reviewer: <name>
- Date: <YYYY-MM-DD>
```

## When the pilot reveals something interesting

Three possible kinds of finding:

1. **Surface improvement** (most common). Wording, order, layout.
   File an issue, add to next docs pass. Do **not** mid-pilot patch.
2. **Pathology** — a telemetry shape we hadn't seen.
   Document in [TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md).
   Add a corresponding test to
   `arip-core/tests/test_calibration_benchmark.py` only after the
   pilot is fully archived.
3. **Trust-layer regression** — ARIP confidently said something wrong.
   This is a release-blocker. Open a P0 issue, halt new pilots until
   resolved. **Almost never mid-pilot patch** — first close out the
   pilot data cleanly, then fix.

## Anti-patterns during a pilot

| Don't do this                                                | Why                                                                |
|--------------------------------------------------------------|--------------------------------------------------------------------|
| "Quick fix" a rule between sessions                          | Invalidates data across sessions                                   |
| Edit the report template to make a finding clearer           | Same                                                               |
| Pre-explain the primary hypothesis before they read it       | Confounds the engineer-trust signal                                |
| Show them the alternatives unless they ask                   | They should discover the layout themselves                         |
| Bring up Datadog / Honeycomb comparisons                     | Positioning conversation, not investigation conversation           |
| Promise features in response to friction                     | Anchors expectations; deferred items go to FUTURE_ARCHITECTURE     |
| Skip Step 7 (anonymisation) "because they said it's fine"   | Hard rule, no exceptions                                           |

## Frequency

One pilot per week is the upper bound. Slower is better. Each pilot's
outcome.md must be reviewed before the next pilot starts.

## Done with this runbook means

`pilot-archive/<pilot-id>/` has all 8 files, `outcome.md` is signed
off, and the metrics in PILOT_METRICS.md are updated to include this
session's numbers.

That session is now part of the corpus that feeds
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md) and
[PILOT_SYNTHESIS_TEMPLATE.md](PILOT_SYNTHESIS_TEMPLATE.md).

After three pilots, run the synthesis exercise.
