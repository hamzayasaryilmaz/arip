# Usability findings — `op002b` (OTel Demo + faults, no logs, RUNNER's notes)

_Findings observed by the validation runner. No human operator
present. See `feedback.md` for warm-up disclaimer._

Most narrative is in
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md);
this file lists only op002b-specific observations.

## Finding 1 — Trust contract enforced as designed (POSITIVE)

- **Observation:** 30 ERROR-status spans, valid cross-service ERROR
  chains in 4 traces, but engine produced 0 rule clusters and 1
  `weak_evidence` cluster (3 occurrences). Reason: only 1 evidence
  kind (span). `MIN_EVIDENCE_KINDS=2` correctly forced abstention.
- **Severity:** Cosmetic (positive — trust contract working).
- **Action:** None. Operator learning is the actionable output:
  Jaeger-only deployments need a log backend joined in (Workflow 2
  in INGESTION_GUIDE.md) to get rule clusters out of observe-mode.

## Finding 2 — flagd accepts only declared variants (MINOR)

- **Observation:** Setting `intlShippingSlowdown.defaultVariant = "on"`
  caused flagd to log an error and reject the file change because
  `on` is not a declared variant for that flag (its variants are
  `5sec` / `10sec` / `off`). Self-corrected by re-editing.
- **Severity:** Minor (operator confusion when toggling flags).
- **Routing:** Out of scope — this is a flagd behaviour, not ARIP.

## Finding 3 — `weak_evidence` cluster correctly captures the affected service set

- **Observation:** The 1 weak_evidence cluster's services list
  (cart, checkout, currency, frontend, frontend-proxy, load-generator,
  payment, ...) is exactly the services touched by the fault-injected
  checkout flow. Even abstaining, the engine still points at the
  right area.
- **Severity:** Cosmetic (positive).
- **Action:** None. Document as "abstention clusters are not
  useless — they're directional hints" in OBSERVE_PILOT_KIT.md.
  (Already implied by the docs; reinforces.)

## Summary

- 3 findings: 2 positive (trust contract works, abstention is
  directional), 1 minor (out-of-scope flagd quirk).
- 0 critical findings.
- 0 fixes applied (the engine behaviour observed is the
  designed behaviour).
