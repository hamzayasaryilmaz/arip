# ARIP field test log — 2026-05-30

Field test of ARIP against a freshly-built realistic e-commerce stack
(api-gateway → order-service → inventory-service + payment-service)
running on Docker Compose with Tempo (traces) + Loki (logs) +
OpenTelemetry Python auto-instrumentation.

This is NOT a runner-self-pilot for the Phase 2 entry gate (there is
no real engineer in the loop). It is a controlled shake-down of the
operator workflow + adapters + rules against telemetry shapes that
ARIP had never been pointed at before.

## Setup

- 4 microservices, FastAPI + opentelemetry-instrument auto-instrumentation
- Telemetry stack: Tempo 2.4 + Loki 2.9 + OTel-Collector 0.96
- Adapters exercised: `bin/tempo-export-to-bundles.py`,
  `bin/loki-export-to-logs.py`
- 10 scenarios, each generating ~10–20 trace bundles
- Total traces evaluated: ~140 across the run

## Headline result

**Before field-test fixes:** 0 / 140 traces produced a primary
hypothesis. Every scenario hit `no_rule_matched` or `weak_evidence`,
including textbook retry-storm and downstream-error patterns.

**After three targeted ARIP patches:** ~20 / 140 traces now produce
primary hypotheses on the same telemetry. retry_storm and
downstream_error rules work end-to-end against OTel-auto-instrumented
Python apps.

## Findings + dispositions

### F1 — Loki adapter dropped 100% of OTel-Python logs · FIXED

**Symptom:** `bin/loki-export-to-logs.py` joined 0 of 120 log lines
into bundles. Every log fell through to `--unmatched-out`.

**Root cause:** Two issues compounded:
1. The OTel Python SDK's Loki exporter writes the trace id as the
   field name `traceid` (lowercase, no underscore) inside the JSON
   log body. The adapter's fallback chain was
   `[trace_key, "traceID", "trace_id"]` — `traceid` was never tried.
2. The OTel-Collector loki exporter sets the service-name label as
   `job` (mapped from `OTEL_SERVICE_NAME`). The adapter checked
   `service_name` / `service` / `app` only, so every log entry got
   `service_name="unknown"`.

**Fix:** Broadened the trace-id fallback chain to include `traceid`,
`trace.id`, `otelTraceID`, and also look inside the `attributes`
sub-dict that the OTel SDK emits. Added `job` and `service.name` to
the service-name lookup. 3 regression tests in
`arip-core/tests/test_loki_adapter.py`.

**Result:** 120 / 120 logs joined after the fix.

### F2 — `latency_vs_db` rule couldn't fire on any HTTP-framework-instrumented app · FIXED

**Symptom:** Scenario 04 (handler sleeps 3s after a fast DB call,
~30× ratio) did not fire `latency_vs_db`. Investigation showed the
rule never matched — `is_handler_span(span)` returned False for
every span.

**Root cause:** Default `NormalizationConfig.handler_operation_patterns`
was `["handle_"]` — a convention from the demo's Go services. Every
real HTTP framework (FastAPI / Express / Spring / etc.) emits
operation names like `POST /orders`, `GET /api/foo`, which do not
contain the substring `handle_`. Default config = effectively dead
rule for the most common deployment shape.

**Fix:** Broadened defaults to include HTTP-method prefixes:
`["handle_", "GET ", "POST ", "PUT ", "DELETE ", "PATCH "]`.
Operators with non-HTTP services can still override entirely in YAML.

**Result:** `latency_vs_db` now matches on the standard auto-instrumented
spans. (Still blocked by F3 in some cases — see below.)

### F3 — Rules pulled only `level==ERROR` logs; missed `WARN` retry signals · FIXED

**Symptom:** retry_storm rule produced a hypothesis with confidence
0.80 and 6 span-kind evidence pieces, but the engine abstained with
`weak_evidence` (`MIN_EVIDENCE_KINDS=2`). 4 perfectly-correlated
`WARN`-level retry logs (`reserve sku=... attempt=3 → 503`) were sitting
in the bundle, all with matching trace_id.

**Root cause:** Rules' log enrichment hardcoded `log.level == "ERROR"`.
Per-attempt transient-failure logs are conventionally `WARN`, not
`ERROR` (because they recovered) — so retry storms produce
high-value log evidence that the rule was silently ignoring.

**Fix:** `retry_storm` now includes `ERROR` + `WARN` + `WARNING`
log levels in evidence (logged at all levels are still filtered by
matching trace_id). `downstream_error` log enrichment also broadened
to match logs by trace_id, not just by the demo-specific
`-service` suffix-stripped service name (which excluded logs from
services not following that naming convention).

**Result:** retry_storm goes from 0 → 6/11 primary hypotheses in
scenario 01; downstream_error goes from 0 → 8/18 in scenario 03.

### F4 — Hygiene findings computed but not surfaced in `arip observe` digest · DOCUMENTED, NOT FIXED

**Symptom:** Scenarios 07 (no traceparent propagation) and 08 (no
business-key propagation) did not show any hygiene findings in their
digests, despite ARIP's `collect_hygiene_findings` being wired into
the observation pipeline.

**Likely root cause:** `collect_hygiene_findings` runs on the *first
valid trace* only, and that first trace was healthy-baseline traffic
(scenario scripts emit baseline before the failure traffic). Also,
for the "no traceparent propagation" case, broken upstream→downstream
propagation produces *disjoint traces* (not orphan spans), and the
hygiene check looks for orphans within a trace — it cannot see the
gap when the services don't share a trace_id at all.

**Recommended fix (future PR):** Run hygiene per-trace on a sample
of N traces; aggregate. Add a new hygiene check for
"trace_fanout_too_narrow": services known to exist (from prior
observation) absent from individual traces.

### F5 — `concurrent_modification` rule did not fire on a clear webhook race · NOT FIXED

**Symptom:** Scenario 06 launches `/checkout` and `/webhook` in
parallel with the same `order.id`. Two separate traces, overlapping
in time, both writing to `orders.id`. Rule did not fire on any of
the 11 traces.

**Likely root cause:** Cross-trace correlation by business key — the
correlator joins traces by `order.id`, but in observation mode the
cross-trace lookup path may not be invoked in the same way. Needs
deeper investigation.

**Recommended fix (future PR):** Trace through the observation
pipeline to confirm cross-trace correlation by business_key works in
observe mode the way it does in `arip investigate` mode.

### F6 — `MIN_EVIDENCE_KINDS=2` is unsatisfiable for span-only anomalies · DOCUMENTED

**Symptom:** `latency_vs_db` correctly identifies the latency
disproportion in scenario 04 (30× ratio detected), but produces only
span-kind evidence. A handler that's slow because of an in-process
sleep produces no error/warn logs, so there's no log evidence to add.
The 2-kinds requirement makes this class of finding inherently
un-primary-able.

**Design tension:** The 2-kinds rule is part of ARIP's trust
contract. Relaxing it risks promoting weak findings to primary. But
some anomaly types are intrinsically single-signal (latency
disproportions, span-tree shape anomalies, etc.).

**Options for future:**
- Per-rule trust contract (latency_vs_db could allow 1 kind at
  high confidence; downstream_error stays at 2).
- Span events count as a separate evidence kind from spans.
- Hold the line: surface as candidate-only, document why.

No change for now — documenting as a known design tension.

### F7 — Default `latency_vs_db` matches healthy traffic as candidates · DOCUMENTED

**Symptom:** With the broader handler patterns from F2, the healthy
baseline (scenario 00) now produces 20 candidate `latency_vs_db`
hypotheses. The trust layer correctly abstains all of them
(weak_evidence), so they don't become primary — but they clutter the
"recurring abstentions" section of the digest.

**Recommended fix (future PR):** Add a minimum handler duration
floor that excludes "fast handlers" outright (currently 50ms; could
raise to 200ms+, or make ratio-and-absolute-duration both required).

### F8 — CLI flag inconsistency: `--out` vs `--digest-out` · DOCUMENTED

`arip investigate` writes its markdown via `--out PATH`.
`arip observe` writes its digest via `--digest-out PATH`.
Different verb + different flag for the same operation. Operators
will guess wrong.

**Recommended fix (future PR):** Either rename `--digest-out` →
`--out` (with deprecation alias), or document both consistently. Easy
fix, defer to a UX-polish PR.

## Round 2 — closing F4 through F9

After the first three fixes (F1, F2, F3), the user asked to close the
remaining gaps too. Six more fixes landed in this second round.

### F4 — Hygiene findings missed disjoint-trace propagation gaps · FIXED

**Symptom:** Scenarios 07 and 08 produced no hygiene findings in
the digest, despite the failure modes being clearly hygiene-relevant.

**Root causes (two):**
1. `collect_hygiene_findings` ran only on the FIRST valid trace. If
   that trace was healthy-baseline traffic (the scenarios warm up
   with baseline calls), the gap-bearing traces later in the stream
   were never checked.
2. Broken traceparent propagation produces *disjoint traces*, not
   orphan spans — services emit telemetry in separate root traces,
   each looking complete from its own perspective. The per-trace
   span-tree gap check cannot see this.

**Fix:** Sample hygiene across the first 20 traces and dedupe findings.
Added a new pipeline-level check `trace_fan_out_narrow`: track the
distinct service set across all bundles; if the source has seen ≥ 4
services overall but some traces touch only one of them, flag it
with example trace IDs.

**Result:** Scenario 07 now emits a clear "Trace fan-out gap" finding
naming the 3 single-service example traces.

### F5 — `concurrent_modification` rule needs cross-trace correlation that observe-mode doesn't do · DOCUMENTED

**Symptom:** Scenario 06 (webhook race) never fired the
`concurrent_modification` rule.

**Root cause:** `arip investigate` mode pulls related traces via
`TimelineBuilder` business-key lookup. `arip observe` mode investigates
each bundle standalone, with `related_trace_ids=[]`. Two racing
traces with the same `order.id` are in separate bundles, so the rule
literally cannot see both at once.

**Disposition:** Documented as a known limitation in the rule's
docstring + added section `11.5 Cross-trace joining in observe-mode`
to `docs/FUTURE_ARCHITECTURE.md` with a build sketch. The full
implementation is ~1 day of work (SQLite index on business_key,
join-on-ingest, span budget) and is justified the first time a real
operator hits this. Field test surfaced it; doc trail makes it
findable when it matters.

### F6 — `MIN_EVIDENCE_KINDS=2` unsatisfiable for single-signal anomalies · FIXED (per-rule policy)

**Symptom:** `latency_vs_db` correctly identifies a 30× handler-to-DB
disproportion but emits span-only evidence (no co-occurring error
logs for "handler is slow" — there's nothing for the log layer to
add). The 2-kind requirement made it un-primary-able.

**Fix:** Added `min_evidence_kinds: int = 2` to `Hypothesis`. Rules
that produce inherently single-kind signals at high confidence may
opt into `min_evidence_kinds=1`. `WEAK_CONFIDENCE_CEILING=0.7`
remains as the other half of the trust contract — opting into
single-kind evidence does NOT bypass the confidence floor.
`latency_vs_db` now sets `min_evidence_kinds=1` because its sharp
thresholds (200ms handler, 5ms-min DB, 10× ratio) already enforce
strong evidence.

**Trust-contract impact:** No regression. The default is unchanged;
the per-rule override is explicit and justified in code; the
existing confidence floor still gates promotion. 3 regression
tests added (`test_fieldtest_fixes.py`).

### F7 — `latency_vs_db` produced false-positive candidates on healthy traffic · FIXED

**Symptom:** Scenario 00 (healthy baseline) produced 20
weak_evidence `latency_vs_db` candidates that cluttered the digest's
"recurring abstentions" section.

**Root cause:** Default thresholds (`MIN_HANDLER_US=50_000`) matched
nearly every healthy auto-instrumented HTTP handler (~80-200ms with
~5ms DB work easily crosses 10× ratio).

**Fix:** Raised `MIN_HANDLER_US` to 200ms (only "actually slow"
handlers qualify) and added `MIN_DB_US=500us` floor to filter
microscopic DB spans where the ratio is meaningless.

**Calibration:** First attempt set `MIN_DB_US=5_000` which
over-corrected — real Postgres INSERTs take 1-3ms each, so a handler
with 2 INSERTs falls below the floor. Re-calibrated to 500us
(0.5ms), which lets real DB work through while still filtering
spans like "0.05ms cached read".

**Result:** Scenario 00 no longer clutters digest with false
candidates; scenario 04 fires 6 primary `latency_vs_db` hypotheses.

### F8 — CLI flag inconsistency `--out` vs `--digest-out` · FIXED

**Fix:** `arip observe` now accepts both `--out` (canonical, matches
`arip investigate`) and `--digest-out` (alias, backwards-compatible).
2 regression tests added.

### F9 — Config YAML loader rejected `business_key_attrs` even though it's the dataclass field name · FIXED

**Symptom (surfaced WHILE writing fieldtest config):** YAML with
`business_key_attrs: [order.id]` errored with `unknown config keys:
['business_key_attrs']`. The internal dataclass field IS named
`business_key_attrs` — but the YAML schema renamed it to
`business_keys`.

**Fix:** Loader now accepts both `business_keys` (canonical) and
`business_key_attrs` (alias matching the dataclass field). Comment
in code explaining why both forms work.

**Side note:** This was a real trap — the documentation gap between
"what the field is called in Python" vs "what the key is in YAML"
is exactly the kind of friction that would make an operator give up
during onboarding.

## Per-scenario verdict table (post-fix)

| # | Scenario | Expected | Round 1 (F1-F3) | Round 2 (F4-F9) | OK? |
|---|---|---|---|---|---|
| 00 | healthy baseline | (no rules) | 0 primary, 20 weak_evidence noise | 0 primary, 20 no_rule_matched (clean) | ✅ |
| 01 | retry storm | retry_storm | **6/11 primary retry_storm** | **6/11 primary retry_storm** | ✅ |
| 02 | pool exhaustion | abstention OR latency_vs_db | 20 abstain | **9/20 primary latency_vs_db** + hygiene findings | ✅ (handler-stalled lens is fair) |
| 03 | downstream error chain | downstream_error | **8/18 primary downstream_error** | **8/18 primary downstream_error** + 5 latency_vs_db | ✅ |
| 04 | latency 30× over DB | latency_vs_db | rule fires + abstains (F6) | **6/10 primary latency_vs_db** | ✅ FIXED via F6 |
| 05 | slow DB query (negative control) | no rule | abstain | abstain (10/10) | ✅ correct silence |
| 06 | concurrent modification (webhook race) | concurrent_modification | not firing | not firing — but hygiene flags it | ⚠️ F5 known limitation |
| 07 | hygiene: stripped traceparent | hygiene finding | no hygiene | **"Trace fan-out gap" finding** | ✅ FIXED via F4 |
| 08 | hygiene: no business-key propagation | hygiene finding | no hygiene | **"Business-key propagation gap" finding** | ✅ FIXED via F4+F9 |
| 09 | mixed failures | multiple primaries | 6/17 primary | **9/17 primary** (3 retry + 3 latency + 3 downstream) | ✅ |

## ARIP patches landed this session

Round 1 (F1-F3):
1. `arip_core/canonical/config.py` — broader `handler_operation_patterns` (F2).
2. `bin/loki-export-to-logs.py` — trace-id + service-name fallback (F1).
3. `arip_core/engine/rules/retry_storm.py` — WARN-level log evidence (F3).
4. `arip_core/engine/rules/downstream_error.py` — trace_id log matching (F3).

Round 2 (F4-F9):
5. `arip_core/observation/pipeline.py` — sample hygiene across first
   20 traces, dedupe, + new `trace_fan_out_narrow` check (F4).
6. `arip_core/engine/rules/webhook_race.py` — docstring documents
   the observe-mode cross-trace requirement (F5).
7. `docs/FUTURE_ARCHITECTURE.md` — new section 11.5 with build
   sketch for cross-trace observe-mode joining (F5).
8. `arip_core/engine/models.py` — `Hypothesis.min_evidence_kinds`
   field (F6).
9. `arip_core/engine/abstention.py` — per-hypothesis kinds floor (F6).
10. `arip_core/engine/rules/latency_vs_db.py` — raised thresholds +
    `min_evidence_kinds=1` opt-in (F6, F7).
11. `arip_core/cli.py` — `arip observe --out` alias + `build_parser()`
    extraction (F8).
12. `arip_core/canonical/config.py` — accept `business_key_attrs`
    YAML key as alias for `business_keys` (F9).

Test files:
- `tests/test_loki_adapter.py` — 3 tests (F1)
- `tests/test_fieldtest_fixes.py` — 7 tests (F6, F7, F8)
- Updated `tests/test_engine_rules.py` for new latency_vs_db thresholds

Test suite: **249 / 249 passing** (was 238 — +11 new tests).

## Operator workflow notes

Things that worked smoothly:
- Tempo HTTP search → fetch → adapter conversion: zero issues.
- `arip observe` ingestion + cursor + idempotent re-runs: solid.
- Docker Compose stack startup: ~15s to all-healthy.

Things that needed manual fixing in my harness:
- `--out` vs `--digest-out` (F8). I had to read `--help` to discover
  the correct flag.
- Loki body trace-id format mismatch (F1). Silent — I only noticed
  because I knew to look at "unmatched logs" output.
- Inventory exhaustion across scenario reruns. Real-world operator
  pain — needs explicit between-run state reset, which I added to
  the harness via a `psql -c "UPDATE inventory SET reserved=0;
  TRUNCATE orders;"` step.

## What this exercise validated

- The Tempo + Loki adapter chain works end-to-end against real-world
  OTel auto-instrumentation, once the field-test-surfaced fallbacks
  are in place.
- ARIP's trust contract held: it preferred to abstain (`weak_evidence`)
  rather than promote a rule with single-kind evidence to primary,
  even when that rule was identifying a real issue. This is correct
  behaviour even though the result was sometimes frustrating.
- The 5-rule engine catches retry_storm and downstream_error
  reliably on standard OTel telemetry, post-fixes.

## What this exercise did NOT validate

- A real engineer trying to use ARIP on their own system (Phase 2
  entry gate condition — still open).
- The Honeycomb / Grafana Cloud / AWS X-Ray adapters' live API paths
  (no accounts; these remain "wire-format-tested-only" per
  `docs/adapter-roadmap.md`).
- Long-running observation (>1 hour windows, cursor resume, etc.).
- Concurrent-modification rule under cross-trace business-key
  correlation (F5).

---

Generated 2026-05-30 by autonomous field test session. Stack and
scenarios in this directory; ARIP fixes committed separately in
`/Users/hamza/Developer/vscode/arip`.
