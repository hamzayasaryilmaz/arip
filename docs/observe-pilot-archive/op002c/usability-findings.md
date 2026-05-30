# Usability findings — `op002c` (OTel Demo + faults + Loki, RUNNER's notes)

_Findings observed by the validation runner. No human operator
present. See `feedback.md` for warm-up disclaimer._

Most narrative is in
[UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md);
this file lists only op002c-specific observations.

## Finding 1 — First rule cluster from an unknown OSS system (MILESTONE)

- **Observation:** `downstream_error` rule fired, high quality
  band, on a trace where:
  - the system was not built by us (OpenTelemetry Demo, CNCF)
  - the fault was real (flagd-injected paymentUnreachable)
  - the trace data came from real Jaeger v2 via the Jaeger adapter
  - the log data came from real `grafana/loki:latest` via the Loki adapter
  - the bundle was assembled by chaining the two adapters
  - the engine path (`engine.investigate()`) was unchanged from the
    investigation-mode CI path
- **Severity:** Milestone-level positive finding. First end-to-end
  integration validation across three independent OSS systems
  (OTel Demo + Jaeger + Loki) feeding ARIP without modification.
- **Action:** Document prominently in
  UNKNOWN_SYSTEMS_VALIDATION.md and README "Proven" table.

## Finding 2 — Loki adapter requires correct stream-label trace_id (CONFIRMED)

- **Observation:** The Loki adapter joins logs by stream-label
  `trace_id`. When we pushed logs with stream labels including
  `trace_id: 87d9b2d1fab2dee4...`, the adapter joined exactly
  the right traces. Zero unmatched logs.
- **Severity:** Cosmetic — confirms the adapter behaviour holds on
  real Loki responses, not just synthetic fixtures.
- **Action:** None. INGESTION_GUIDE.md already documents the
  stream-label convention.

## Finding 3 — Quality band lift from medium to high (POSITIVE)

- **Observation:** op002b had 0 high-band observations. op002c
  has 1 high-band observation — exactly the one with joined logs.
  The quality assessor correctly attributes the band lift to
  `log_trace_correlation` coverage moving from 0 to 1.
- **Severity:** Cosmetic (positive — quality scoring works on
  real telemetry).
- **Action:** None.

## Finding 4 — The 2 `weak_evidence` clusters that remained

- **Observation:** op002b had 3 weak_evidence cluster occurrences.
  op002c has 2. The 1 that collapsed corresponds to the trace
  whose logs were joined. The remaining 2 are traces with ERROR
  chains but no log correlation (other fault-injected traces; we
  only pushed logs for 1 trace_id).
- **Severity:** Cosmetic — directly confirms the cause-and-effect.
- **Action:** None. Confirms the trust contract is
  per-observation, not per-batch.

## Summary

- 4 findings: 1 milestone positive, 3 cosmetic positive.
- 0 negative findings.
- 0 critical findings.
- 0 fixes needed.

This is the cleanest validation run since the project started.
Everything worked as designed, end-to-end, on telemetry from a
system the engine had never seen, with real adapters bridging real
backends.

**Still a runner-self-pilot.** Real engineer pilot (op004) remains
the bar for Phase 2 entry gate.
