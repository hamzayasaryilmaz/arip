# Usability findings — `op002` (OpenTelemetry Demo, RUNNER's notes)

_Findings observed by the validation runner. No human operator
was present; these notes are about the **workflow itself**, not
about an operator's experience. See `feedback.md` for full
warm-up disclaimer._

Cross-system synthesis (incl. how this finding relates to op001 +
op003) lives in
[docs/UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md).

## Finding 1 — Service-set cardinality cluster explosion (CRITICAL → fixed)

- **Observation:** 291 traces from OTel Demo's 16-service mesh
  produced **23 distinct abstention clusters**, all `no_rule_matched`.
  Each cluster was a unique combination of services touched by
  different request paths through the mesh.
- **Where:** `arip_core/observation/clustering.py::_abstention_fingerprint`
- **Severity:** **Critical** — the digest became unreadable on a
  realistic mid-sized OSS workload. Cluster explosion under noise
  is the specific failure mode the validation suite exists to
  catch.
- **Fix applied (this iteration):** Abstention fingerprint now uses
  *entry-point services only* (root spans + spans whose parent is
  missing from the bundle). Full transitive set still recorded as
  cluster metadata.
- **Effect:** 23 clusters → 8 clusters. Digest readable again.
- **Regression test:** `tests/test_observation_stress.py::test_abstention_fingerprint_collapses_high_service_count`
- **Routing:**
  - [x] Engine narrow fix (NOT a new capability — narrowing existing fingerprint)
  - [x] Regression test
  - [x] Docstring expanded with op002 rationale

## Finding 2 — Jaeger v2 base_path is hardcoded in adapter docs (MINOR)

- **Observation:** OTel Demo configures its embedded Jaeger with
  `base_path: /jaeger/ui`. The Jaeger HTTP API is then under
  `/jaeger/ui/api/...` not `/api/...`. The runner had to inspect
  Jaeger's config to discover this.
- **Where:** `docs/INGESTION_GUIDE.md` Workflow 1 examples
- **Severity:** Minor — a real operator would hit this in 5
  minutes via 404 responses and figure it out.
- **Proposed surface fix:** INGESTION_GUIDE.md to mention "Jaeger
  v2 deployments often use a `base_path`; check via the Jaeger
  config or via `curl <jaeger>/`'s response body".
- **Routing:**
  - [x] INGESTION_GUIDE.md update

## Finding 3 — Random Jaeger host port via Docker port allocation (COSMETIC)

- **Observation:** OTel Demo's Jaeger UI bound to host port 60597
  (random) instead of the default 16686. The runner had to
  `docker ps | grep jaeger` to find the actual port.
- **Severity:** Cosmetic — standard Docker Compose behaviour when
  the compose file doesn't pin the host port.
- **Proposed surface fix:** None. INGESTION_GUIDE.md's curl
  examples already use `localhost:16686` as placeholder; operators
  understand placeholder semantics.

## Finding 4 — `oteldemo.CartService/GetCart` operation names don't match `handler_` pattern (REPEAT from op001)

- **Observation:** Same pathology as HotROD op001 — handler
  operation names don't include `handle_` substring, so
  `latency_vs_db` cannot identify entry-point spans.
- **Severity:** Major (now seen on a second system).
- **Status:** Already documented in OBSERVE_PILOT_KIT.md
  pre-pilot checklist. Strengthens the existing guidance with a
  second real-world example.
- **Routing:**
  - [x] OBSERVE_PILOT_KIT.md update (add OTel-Demo-style RPC
        operation names as a third common-override example)

## Findings explicitly NOT made

The following were observed but NOT recorded as findings:

- **"No rule clusters fired"** — by design; healthy OTel Demo
  traffic has no anomaly shape any of the 5 rules' contracts
  match. Honest abstention, not a defect.
- **"Could ARIP support OTel Demo's flagd-based fault injection
  natively?"** — out of scope; would be telemetry-repair, anti-goal.
- **"Could ARIP generate a `cart_service_failure` rule
  specifically for OTel Demo?"** — explicit Phase A freeze
  (new rules frozen until Phase 2 entry gate clears).

## Summary

- Total findings: **4**
  - Critical: 1 (Finding 1, fixed)
  - Major: 1 (Finding 4, already documented)
  - Minor: 1 (Finding 2, surface fix)
  - Cosmetic: 1 (Finding 3, no action)

The critical finding was a real engine defect, caught by validation
against a realistic OSS workload, fixed within the same iteration
with a regression test pinning the corrected behaviour.

This is the third "fingerprint cardinality" defect caught and fixed
during validation (after PHASE_A_VALIDATION Appendices A and B).
The pattern is now part of the project's institutional knowledge:
any cardinality dimension that grows with telemetry complexity must
NOT be in the fingerprint.
