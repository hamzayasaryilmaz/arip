# Usability findings — `op001` (HotROD warm-up, RUNNER's notes)

_Findings observed by the validation runner while running observe-mode
end-to-end against HotROD. No human operator was present; these notes
are about the **workflow itself**, not about an operator's experience
of it._

> Important: anywhere this file uses "the operator", read it as "a
> hypothetical operator running the same workflow". The runner is not
> an operator. See `feedback.md` for the warm-up disclaimer.

## Finding 1 — Default `handler_operation_patterns` doesn't match HotROD

- **Observation:** The default `arip-core/configs/demo.yaml` sets
  `handler_operation_patterns: ['handle_']`. HotROD handlers are
  `/dispatch`, `/customer`, `/route`, `GetDriver`, `FindDriverIDs`,
  none of which match `handle_`. As a result, the `latency_vs_db`
  rule cannot identify entry-point spans and abstains across all
  40 HotROD traces.
- **Where:** `arip-core/configs/demo.yaml` line 39-41, surfaced via
  `latency_vs_db` rule contract in `arip-core/arip_core/quality/contracts.py`.
- **Severity:** Major (a real rule the engine could fire on doesn't,
  silently — an operator would only discover this by inspecting the
  rule contract or comparing telemetry-summary.md tables).
- **Proposed surface fix:** Mention in [docs/OBSERVE_PILOT_KIT.md](../../OBSERVE_PILOT_KIT.md)
  under the pre-pilot checklist: *"if your handler operation names
  do not contain `handle_`, you will need a config override before
  `latency_vs_db` will fire — see [docs/ONBOARDING.md](../../ONBOARDING.md)
  Workflow 5"*. This is a docs-only fix; the config knob already
  exists.
- **Routing:**
  - [x] OBSERVE_PILOT_KIT.md update
  - [ ] Engine change (NOT applicable — config knob already exists)

## Finding 2 — Digest "operations" column is helpful for diagnosing pattern 1

- **Observation:** The digest's abstention cluster row showed
  `operations: /customer, /dispatch, /route, FindDriverIDs (+4)` —
  enough information for the runner to immediately spot that none
  match `handle_*`. Without this column the diagnosis would have
  required digging into the raw bundles. Useful.
- **Where:** `arip_core/observation/digest.py::_write_abstention_table`
- **Severity:** Cosmetic (positive finding).
- **Proposed surface fix:** None. Working as intended.
- **Routing:** None.

## Finding 3 — Cluster cap of 4 names in digest hides the rest

- **Observation:** Same abstention row had `(+4)` after the listed
  operations. The runner had to query the bundles directly to see
  what those 4 were (`HTTP GET`, `SQL SELECT`, `GetDriver`,
  `driver.DriverService/FindNearest`). For a 40-trace pilot, losing
  half the operation names to the cap is OK; for a 4000-trace
  pilot, this cap might bury useful information.
- **Where:** `arip_core/observation/digest.py::_join` (limit=4 for
  abstention table)
- **Severity:** Minor (trade-off, not a bug).
- **Proposed surface fix:** Probably none right now. If a real
  operator hits this at scale, raise the cap to 8 or add a tiny
  `--operations-cap` flag. Premature optimisation otherwise.
- **Routing:** None pending pilot signal.

## Finding 4 — Self-audit's "common causes" guidance is too narrow

- **Observation:** `bin/observe-self-audit.sh`'s closing block lists
  4 interpretation hints (`high band → healthy`, `medium/low → fix
  telemetry`, etc). None of the hints cover "100% abstention because
  the rules genuinely don't apply to this telemetry shape". For
  HotROD that's the actual answer; the operator would have to read
  OBSERVE_MODE.md to learn that abstention can be honest output.
- **Where:** `bin/observe-self-audit.sh` (final `cat <<'EOF'` block)
- **Severity:** Minor (extra step to reach correct interpretation).
- **Proposed surface fix:** Add one bullet to the hint block:
  *"- 100% `no_rule_matched` clusters → your telemetry shape may not
  match any of the 5 rules' contracts; this is honest abstention,
  not a bug"*.
- **Routing:**
  - [x] `bin/observe-self-audit.sh` wording tweak

## Finding 5 — Per-pilot store path lives under .arip/, gitignored correctly

- **Observation:** `bin/run-observe-pilot.sh` wrote `.arip/observation-op001.db`
  during the pilot. `.gitignore` catches `.arip/` so this didn't
  accidentally get staged. Confirmed clean.
- **Severity:** Cosmetic (positive finding).
- **Proposed surface fix:** None.
- **Routing:** None.

## Findings that did NOT make the list

The following observations from this warm-up are NOT recorded as
usability findings because they're either out-of-scope or already
documented:

- "Engine produces no rule clusters" — by design; HotROD's signals
  don't match the rules' contracts. This is the trust contract
  working, not a bug.
- "Could ARIP auto-suggest config overrides" — out of scope; would
  cross into "telemetry repair magic" anti-goal.
- "Could ARIP generate a HotROD-shaped rule" — explicit Phase A
  freeze item (new rules frozen until Phase 2 entry gate clears).

## Summary

- Total findings: **5**
  - Critical:   0
  - Major:      1   (Finding 1, docs fix)
  - Minor:      2   (Findings 3 and 4)
  - Cosmetic:   2   (Findings 2 and 5, positive)

`Critical + Major = 1` — well below the threshold of 3 that would
indicate "digest first-pass usability not yet pilot-ready". The
one major finding is a docs gap, not an engine defect.

The pilot machinery itself worked end-to-end on first try:
self-audit + observe + archive scaffold all succeeded on a system
ARIP had never seen.
