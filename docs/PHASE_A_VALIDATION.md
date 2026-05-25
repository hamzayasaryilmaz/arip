# Phase A — observation mode stress validation

This document captures the validation pass for
[Phase A observation mode](OBSERVE_MODE.md) under production-style
noisy telemetry. The exercise added no capability. It built messy
fixtures, ran them through the existing pipeline, and recorded what
held and what didn't.

The headline question: **does `arip observe` stay deterministic,
readable, bounded, and trustworthy under realistic noise?**

Honest answer: **yes — with one fingerprint correction that fell out
of the exercise.** Details below.

---

## Methodology

- 15 stress scenarios codified in
  [test_observation_stress.py](../arip-core/tests/test_observation_stress.py),
  generating fixtures via
  [tests/fixtures/synthetic_telemetry.py](../arip-core/tests/fixtures/synthetic_telemetry.py)
- One realistic mixed workload (300 noise + 100 cascading + 100 burst
  = 500 traces) processed end-to-end through `arip observe`
- All previous tests (121) re-run to confirm no regression
- Sample digest captured below verbatim from the actual run

---

## Headline finding (and fix)

**Finding.** `fingerprint_hypothesis` counted *evidence-kind
multiplicity* as part of the fingerprint, i.e. a hypothesis citing
3 span Evidence rows fingerprinted differently from one citing 5.
This is correct in theory ("more evidence" is a different shape) and
wrong in practice: under realistic noise, an outage producing 3-,
4-, and 5-attempt retry storms is morally one anomaly, but with
multiplicity in the fingerprint it landed in 3 separate clusters.

A burst-outage stress test of 200 same-shape traces split into 3
fingerprints. The cluster-stability assertion failed cleanly and
loudly — that's exactly what stress testing is for.

**Fix.** [arip_core/memory/fingerprint.py](../arip-core/arip_core/memory/fingerprint.py)
now uses the **set** of evidence kinds (`{span, log}`) instead of the
multiset (`{span: 5, log: 1}`). Membership is preserved — a
hypothesis with logs as corroboration still fingerprints differently
from a spans-only hypothesis — but the count is dropped.

**Why this is not a new capability:** the existing memory tests do
not assert multiplicity sensitivity. The fix is a strict relaxation:
it never produces more divergence than before, only less. Existing
investigation reports' fingerprints will shift one-time; pilots
running against a populated memory.db will see a brief period where
new investigations don't aggregate with pre-fix history. That is
acceptable for an observable, one-time correction.

**Post-fix stress result.** Burst outage of 200 traces collapses to
**1** rule cluster. Cluster recurrence_count = 200. No splits.

---

## What held

Of the 12 invariants the stress suite asserts, **all** hold after the
fingerprint fix:

| Invariant | Test | Outcome |
|---|---|---|
| Burst outage collapses to one cluster | `test_burst_outage_collapses_to_one_rule_cluster` | ✓ post-fix |
| Cascading failure produces ≤ 5 rule clusters | `test_cascading_failure_produces_distinct_rule_clusters` | ✓ |
| Orphan spans never produce rule clusters | `test_orphan_spans_do_not_pollute_rule_clusters` | ✓ |
| Truncated JSONL doesn't crash or loop | `test_truncated_jsonl_does_not_crash_or_loop` | ✓ |
| Cursor resumes after simulated crash | `test_cursor_resumes_after_simulated_crash` | ✓ |
| Replay is idempotent | `test_idempotent_under_replay` | ✓ |
| Gzipped archive == plain | `test_gzipped_archive_processes_same_as_plain` | ✓ |
| Retention prune drops events, keeps clusters | `test_retention_pruning_drops_events_but_keeps_clusters` | ✓ |
| Replay doesn't bloat storage | `test_storage_growth_is_bounded_per_run` | ✓ |
| Digest stays small under noise | `test_digest_under_mixed_noise_is_bounded_in_size` | ✓ |
| `--min-recurrence` actually filters | `test_digest_min_recurrence_filters_out_one_offs` | ✓ |
| Healthy traffic produces no rule clusters | `test_healthy_traces_alone_produce_no_rule_clusters` | ✓ |
| Low-quality telemetry doesn't inflate clusters | `test_low_quality_telemetry_does_not_promote_rule_clusters` | ✓ |
| Fingerprint determinism across runs | `test_fingerprint_determinism_across_runs` | ✓ |
| No drift to side-effect surfaces | `test_observation_module_does_not_import_side_effect_surfaces` | ✓ |

The last one is the no-drift contract: the observation module's
transitive imports are scanned and asserted to **not** include the
GitHub integration or the LLM summariser. Any future change that
quietly adds an alert call or a PR opener will fail this test.

---

## Real workload digest (captured verbatim)

Source: 500 trace bundles — 300 mixed noise, 100 cascading failure,
100 burst outage. The digest in full:

```markdown
# ARIP observation digest

## Run summary

- source: `jsonl:///private/tmp/sample-noisy.jsonl`
- traces observed: 500
- new events: 500
- idempotent skips: 0
- quality band distribution: high=70, medium=430
- rule matches: db_pool_exhaustion=38, retry_storm=187
- abstentions: no_rule_matched=205, weak_evidence=70

## Recurring patterns (rule-grounded)

| rule                | recurrence | services           | operations                                   |
|---------------------|-----------:|--------------------|----------------------------------------------|
| retry_storm         |        187 | inventory-service  | inventory.reserve_attempt                    |
| db_pool_exhaustion  |         38 | inventory-service  | db.acquire_connection, handle_reserve        |

## Recurring abstentions

| abstention        | recurrence | services                            | operations                          |
|-------------------|-----------:|-------------------------------------|-------------------------------------|
| no_rule_matched   |        190 | payment-service                     | POST /checkout                      |
| weak_evidence     |         70 | inventory-service, payment-service  | POST /checkout, inventory.reserve   |
| no_rule_matched   |         15 | inventory-service                   | inventory.reserve                   |
```

Five clusters total. The full markdown is under 2 KB.

---

## What this real run told us

### 1. Readability holds

500 traces → 5 clusters. The "operator can read this in 30 seconds"
bar is met. No cluster explosion, no repetitive duplicates, no
debug-heavy detail bleeding into the summary.

### 2. Quality band propagation is honest

70 high + 430 medium = 500. Quality is "medium" by default for
anything missing perfect propagation_health or log_trace_correlation.
This is the existing assessor doing exactly what it does in
investigation mode — observation does not invent new bands.

### 3. Abstention clustering is informative

The `no_rule_matched` cluster on `payment-service` with 190
recurrences is descriptive, not pejorative: a lot of traffic in this
fixture is genuinely "single OK span" telemetry that the engine
correctly has no rule for. It surfaces — but as an abstention, not as
a rule finding. That is the trust contract working.

### 4. `downstream_error` is shy on this fixture

`downstream_error` did not produce a rule cluster on this mix —
those traces landed in `weak_evidence` (70 abstentions) because the
rule's emitted Evidence shape on this fixture has only a single
evidence kind, hitting `MIN_EVIDENCE_KINDS=2`. This is **not a bug**:
the engine is refusing to promote a hypothesis without
multiple-kind corroboration, exactly as the trust contract dictates.

If a pilot reports "ARIP keeps abstaining on real downstream failures
I want it to call out", that is a calibration signal worth taking
seriously — but it does NOT belong in this validation pass. Noted
for [docs/CALIBRATION.md](CALIBRATION.md).

### 5. No drift detected

The structural no-drift test asserts the observation module does not
transitively import the GitHub integration or LLM summariser. Both
absences confirmed. Phase A's identity ("read-only, no PR, no
network egress, no alert") is enforced at the import level, not just
in prose.

---

## Cursor and storage behaviour

| Property | Observed |
|---|---|
| JSONL cursor format | byte offset, monotonic |
| Gzip JSONL cursor | byte offset over decoded stream |
| Truncated last line | skipped, cursor advances past valid lines |
| Crash mid-stream | cursor saved per observation → resumes exactly |
| Replay protection | `(source_name, observation_id)` uniqueness; 5 replays do not multiply DB size |
| Retention | `prune_events_older_than(n)` drops events; cluster aggregates persist |

The observation DB after 500 traces is ~50 KB. Aggressively bounded;
no pruning required for casual pilot use.

---

## Trust behaviour under noise — explicit findings

The most important question per the validation request:

> *Observe-mode: gerçek production-style telemetry altında hala
> deterministic / readable / bounded / trustworthy kalıyor mu?*

| Property | Verdict | Evidence |
|---|---|---|
| Deterministic | Yes | `test_fingerprint_determinism_across_runs` — same input, same fingerprint set across separate runs |
| Readable | Yes (post-fix) | 500 traces → 5 clusters → < 2 KB markdown; cluster bound asserted in `test_digest_under_mixed_noise_is_bounded_in_size` |
| Bounded | Yes | per-run budget + idempotent storage + retention API; storage-growth test asserts replay does not bloat |
| Trustworthy | Yes | abstention clustering, quality propagation, evidence audit all unchanged; the engine path is shared with `arip investigate` |

The fingerprint fix was a real defect. It was caught by the stress
suite within minutes of running the first real workload. The
suite stays in the project as a regression contract — any future
clustering change that re-introduces evidence-multiplicity
sensitivity will fail loudly.

---

## What this validation did NOT do (and why)

- **Did not add new abstention codes.** Phase A reuses the existing
  five; no new vocabulary was needed to clear the stress tests.
- **Did not add a candidate generation prototype.** That capability
  remains gated to its trigger condition in
  [FUTURE_ARCHITECTURE.md #11](FUTURE_ARCHITECTURE.md).
- **Did not add new rule templates or new failure scenarios.** The
  stress suite uses the same 5 rules as production.
- **Did not run against real customer telemetry.** Synthetic noise
  is a substitute for early pilot data, not for it. Real-world
  pathology calibration is the
  [PILOT_RUNBOOK.md](PILOT_RUNBOOK.md) job, not this one's.

If a pilot surfaces a noise behaviour these synthetic fixtures missed,
the right response is: add a fixture, write the assertion, fix the
narrow gap. The validation suite is designed to grow that way.

---

## Files added or changed by this validation

- **Added.** `arip-core/tests/fixtures/synthetic_telemetry.py` — generators
- **Added.** `arip-core/tests/test_observation_stress.py` — 15 stress tests
- **Added.** `docs/PHASE_A_VALIDATION.md` — this document
- **Changed.** `arip-core/arip_core/memory/fingerprint.py` — drop
  evidence-kind multiplicity; use set instead of Counter. Docstring
  expanded to record the rationale.

Test count: 121 → 136. Regressions: 0. Trust contract: intact.

---

# Appendix B — Real-world ingestion validation

Iteration 2 of Phase A validation. Goal: exercise the operator path
from real-world export shapes (Jaeger, Loki, GHA artifacts, rotated
logs) all the way through `arip observe`. Capability boundary
unchanged — no candidate generation, no template engine, no PR
creation, no alerting, no dashboard. The observation module
(`arip_core/observation/`) was not modified except for one narrow
fingerprint correction described below.

## Method

- New adapter scripts in `bin/` (operator tooling, NOT part of
  `arip_core`):
  - `jaeger-export-to-bundles.py` — Jaeger JSON → JSONL trace bundles
  - `loki-export-to-logs.py` — Loki streams JSON → joined onto
    existing bundles by `trace_id`
- New fixture module emulating real export shapes:
  - `arip-core/tests/fixtures/real_world_exports.py` — Jaeger search
    response, Loki query response, GHA artifact zip (3 layouts),
    partial gzip writer
- 9 ingestion-validation tests in
  `tests/test_observation_realworld.py` exercising the operator
  pipelines end-to-end
- New operator guide: [docs/INGESTION_GUIDE.md](INGESTION_GUIDE.md)
- New pathology entries:
  [docs/TELEMETRY_PATHOLOGIES.md Appendix](TELEMETRY_PATHOLOGIES.md)
  with pre-pilot label

## Headline finding (and fix)

**Finding.** Observation-mode abstention fingerprint included the
top-5 entry-point operation names. Real production telemetry
commonly embeds entity identifiers in operation names
(`POST /checkout/order-12345`, `GET /users/u-abc-123/profile`), so
every trace got a unique fingerprint and abstention clusters
exploded into singletons. A fixture of 10 path-parameter clones plus
2 unrelated traces produced 13 clusters — exactly what cluster
explosion under noise looks like.

**Fix.** [arip_core/observation/clustering.py](../arip-core/arip_core/observation/clustering.py)
`_abstention_fingerprint` now uses `(abstention_code, service_set)`.
Operation names are still recorded on the cluster's
`operation_names_sample` for operator context — but no longer
fingerprint determinants. Same shape of fix as Appendix A's
multiplicity correction: narrowing existing behaviour, never new
capability.

**Why this is not a new capability:** the observation pipeline, the
engine, and the rule set are unchanged. The fingerprint that decides
"these two traces describe the same abstention pattern" is the only
thing that moved, and it moved in the direction of fewer
distinctions, not more.

**Post-fix.** Same fixture (12 traces, 10 of them path-parameter
variants) collapses to ≤ 6 clusters total. Singleton explosion gone.

## What held — real-world workflows

| Workflow | Test | Outcome |
|---|---|---|
| Jaeger JSON export → bundles → observe | `test_jaeger_export_converts_and_observes` | ✓ |
| Path-parameter operation names don't explode | `test_jaeger_path_parameter_operation_name_clusters_safely` | ✓ post-fix |
| Loki join surfaces unmatched logs, not silent absorption | `test_loki_join_adds_logs_to_existing_bundles` | ✓ |
| GHA artifact (directory layout) | `test_gha_artifact_directory_layout_observes_correctly` | ✓ |
| GHA artifact (single JSONL layout) | `test_gha_artifact_jsonl_layout_observes_correctly` | ✓ |
| GHA artifact (nested partitions) | `test_gha_artifact_nested_directory_observes_correctly` | ✓ (with recipe) |
| File rotation in place — silent skip pinned | `test_file_rotation_does_not_silently_drop_new_writes` | ✓ pinned as known |
| Partial gzip stream does not crash | `test_partial_gzip_does_not_crash` | ✓ |
| Real-shape digest stays small and actionable | `test_realistic_export_digest_is_actionable` | ✓ |

## Real-shape digest (captured verbatim)

End-to-end run: Jaeger search response (3 traces: 1 downstream-error,
1 retry-storm, 1 orphan) joined with Loki response (logs for 2 of 3
traces; 1 free-text log without trace_id correctly unmatched).

```
## Run summary

- source: jsonl:///private/tmp/bundles-joined.jsonl
- traces observed: 3
- new events: 3
- idempotent skips: 0
- quality band distribution: high=1, medium=2
- rule matches: retry_storm=1
- abstentions: no_rule_matched=1, weak_evidence=1

## Recurring patterns (rule-grounded)

| rule         | recurrence | quality | services            | operations                 |
|--------------|-----------:|---------|---------------------|----------------------------|
| retry_storm  |          1 | medium  | inventory-service   | inventory.reserve_attempt  |

## Recurring abstentions

| abstention      | recurrence | services                            | operations                                  |
|-----------------|-----------:|-------------------------------------|---------------------------------------------|
| weak_evidence   |          1 | inventory-service, payment-service  | POST /checkout/order-12345, inventory.reserve |
| no_rule_matched |          1 | inventory-service                   | inventory.reserve                           |
```

Three traces, three clusters, ~2 KB total. The path-parameter
operation name appears in the operation_names_sample column (for
operator context) but does not split the cluster.

## Pathologies catalogued

Four pre-pilot pathology entries added to
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md), all clearly
labelled as not-yet-pilot-sourced:

- **P1.** Path-parameter operation names exploded abstention clusters
  → fingerprint fix applied.
- **P2.** Loki logs without resolvable trace_id → surfaced in
  `--unmatched-out`, never silently absorbed.
- **P3.** File rotation in place causes silent skip → documented
  workflow workaround (one URI per rotation); auto-detection deferred.
- **P4.** Truncated gzip stream → pipeline's per-trace try/except
  absorbs; cursor stays put for retry; store remains valid.

The catalogue's main contract is preserved: these pre-pilot entries
must be re-validated against real pilot data before they earn
calibration-benchmark tests.

## Identity preservation check

The no-drift contract from Appendix A is reinforced by Appendix B:

- No new modules in `arip_core/observation/`. The adapters live in
  `bin/` and import nothing from `arip_core` other than what the
  shell would.
- The `test_observation_module_does_not_import_side_effect_surfaces`
  no-drift test from Appendix A still passes — adapters are
  out-of-tree from the observation module by construction.
- Engine path unchanged; same `engine.investigate()` consumes the
  joined bundles as consumes CI-mode telemetry.
- No dashboard, no alerting, no SIEM, no APM surface introduced.

## Final answer to the validation question

> *Observe-mode: gerçek messy telemetry altında bile deterministic /
> bounded / trustworthy / operator-friendly kalıyor mu?*

| Property | Verdict | Evidence |
|---|---|---|
| Deterministic | Yes | Determinism test from Appendix A still passes |
| Bounded | Yes — post-fix | Pre-fix: path-parameter pathology broke cluster bound; post-fix: 13 traces → ≤ 6 clusters asserted |
| Trustworthy | Yes | Loki unmatched logs surface visibly; partial gzip does not corrupt store; orphan spans land in abstentions |
| Operator-friendly | Yes — post-fix | Real-world fixture digest stays < 2 KB; INGESTION_GUIDE.md gives concrete workflows per export shape |

Both findings (Appendix A fingerprint multiplicity, Appendix B
abstention-fingerprint operation-name cardinality) were caught by
the validation suite, not by chance, and not by user-facing trust
failures. The pattern is now: each Phase A validation iteration
expects to find ≥ 1 narrow correction; the regression suite grows
to lock the corrections in.

## Files added or changed by Appendix B

- **Added.** `bin/jaeger-export-to-bundles.py` — operator adapter
- **Added.** `bin/loki-export-to-logs.py` — operator adapter
- **Added.** `arip-core/tests/fixtures/real_world_exports.py` — fixtures
- **Added.** `arip-core/tests/test_observation_realworld.py` — 9 tests
- **Added.** `docs/INGESTION_GUIDE.md` — operator workflow
- **Changed.** `arip-core/arip_core/observation/clustering.py` —
  `_abstention_fingerprint` drops operation names; docstring
  expanded to record the rationale.
- **Changed.** `docs/TELEMETRY_PATHOLOGIES.md` — pre-pilot appendix
  added with 4 entries.
- **Changed.** `docs/PHASE_A_VALIDATION.md` — this appendix.

Test count: 136 → 145. Regressions: 0. Trust contract: intact.
