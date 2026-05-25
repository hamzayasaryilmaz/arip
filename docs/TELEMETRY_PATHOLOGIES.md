# Telemetry pathologies

A live catalogue of *real-world* telemetry shapes that pilots have
exposed. Each entry comes from a pilot session — never from
speculation, never from a synthetic example.

The catalogue's purpose is twofold:

1. **A reference for the onboarding owner.** When configuring ARIP
   for a new environment, this is the list of "things to look out
   for in your telemetry."
2. **A source for the calibration benchmark.** Pathologies that
   appear in ≥ 2 independent pilots earn a synthetic test in
   `arip-core/tests/test_calibration_benchmark.py` that locks in
   ARIP's expected response.

## Current status

> **No pathologies catalogued yet — zero pilots completed.**
>
> The structure below is the empty-but-ready template. Each
> category is a known *class* of telemetry problem; entries inside
> each category come from real pilots.

## How to add an entry

When a pilot exposes a new pathology, append an entry to the
relevant category below using this shape:

````markdown
### <short pathology name>

**First observed:** pilot `<p###>`, <date>
**Subsequent observations:** pilot `<p###>` (<date>)
**Affected rules / signals:** <which rules' contracts are weakened>

**What the telemetry looks like:**

```text
<concise structural description; include a representative span
attribute set or log line shape. NOT the verbatim pilot data —
that lives in pilot-archive/<p###>/spans.json.>
```

**Why ARIP encounters it:**

> One paragraph on why this shape exists in real systems (e.g.
> "this is what Spring auto-instrumentation emits when…").

**ARIP's current behaviour:**

> Verbatim: which rules fire, which abstain, which confidence is
> produced. Be specific.

**Verdict:**

- [ ] Behaviour is honest — abstention or low-confidence is the
      right answer. No change needed.
- [ ] Behaviour is misleading — primary fires but framing is
      partial. Surface improvement needed (docs / template).
- [ ] Behaviour is wrong — confidently incorrect primary. Trust
      regression. P0.

**Catalogue test:** (only if seen in ≥ 2 independent pilots)
`tests/test_calibration_benchmark.py::test_scenario_<name>`
````

A pathology entry without a pilot ID is invalid and must be removed.

## Category 1 — Missing attributes

Spans that omit attributes ARIP's rules expect.

> *No entries yet. Add via the template above after a pilot exposes a
> missing-attribute case (e.g. retry spans without `retry.reason`,
> business-keyed entry spans without the key, …).*

## Category 2 — Broken propagation

`parent_span_id` references a span that is not in the telemetry
slice ARIP sees. Either dropped by sampling, or the parent service
isn't instrumented, or the propagator failed.

> *No entries yet.*

## Category 3 — Duplicate spans

The same span emitted twice (double-export from misconfigured OTel
SDKs, parallel processors, etc.).

> *No entries yet.*

## Category 4 — Retry ambiguity

Retry-like patterns where the metadata is incomplete or
inconsistent — e.g. attempts numbered non-monotonically, retry
attribute names that drift, or retries that look distinct because
each is emitted from a different worker.

> *No entries yet.*

## Category 5 — Inconsistent naming within a trace

Different services within the same trace using different attribute
names for the same logical concept (`order.id` vs `order_id`,
`http.status_code` vs `http.response.status_code`, …).

> *No entries yet.*

## Category 6 — Sampled traces

Only a subset of spans visible to ARIP because of head- or
tail-sampling at the producer or collector. Includes "OK trace
sampled out entirely" and "partial chain with middle attempts
missing".

> *No entries yet.*

## Category 7 — Partial / desynced logs

Log entries missing `trace_id` (cannot be correlated), log entries
emitted with the wrong trace_id (cross-talk), or logs whose
timestamps drift relative to spans.

> *No entries yet.*

## Category 8 — Other

Pathologies that don't cleanly fit Categories 1–7. Use this
sparingly; if a pattern repeats in this bucket, promote it to its
own category.

> *No entries yet.*

## Cross-references

- [docs/CALIBRATION.md](CALIBRATION.md) — the trust contract these
  pathologies stress-test
- [docs/calibration-gallery.md](calibration-gallery.md) — the
  synthetic-fixture versions of pathology classes
- [arip-core/tests/test_calibration_benchmark.py](../arip-core/tests/test_calibration_benchmark.py)
  — programmatic guards built from this catalogue
- [docs/PILOT_RUNBOOK.md](PILOT_RUNBOOK.md) — how pilots feed into
  this file

## Discipline

- An entry without a real pilot reference is invalid. Remove it.
- An entry that recurs in ≥ 2 pilots should have a calibration
  benchmark test. Open an issue if it does not.
- A pilot that surfaces no new pathologies still gets archived. Not
  every pilot adds to this catalogue.
- Speculative pathologies ("what if a customer has X?") belong in
  [FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md), not here.

---

## Appendix — Pre-pilot ingestion-validation findings

> **These entries are not pilot-sourced.** They came from the Phase A
> real-world ingestion validation pass (see
> [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) Appendix B). They are
> observed behaviour against fixtures emulating actual export shapes
> (Jaeger HTTP API JSON, Loki query streams, GHA artifact zips), not
> against real customer telemetry. The catalogue's main contract still
> holds: these entries must be re-validated against pilot data before
> they earn calibration-benchmark tests.

They are recorded here (rather than in
[FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md)) because they are
**observed behaviour**, not speculation. The category structure
matches Category 1–8 above; only the source label differs.

### Pre-pilot P1 — Path-parameter operation names exploded abstention clusters

**First observed:** Phase A real-world validation, 2026-05-22
**Source:** synthetic Jaeger search response with 10× clones varying
`POST /checkout/order-99000` through `…order-99009`
**Affected layer:** observation-mode abstention fingerprint
(`arip_core/observation/clustering.py::_abstention_fingerprint`)

**What the telemetry looks like:**

```text
operation_name: POST /checkout/order-12345
operation_name: POST /checkout/order-12346
operation_name: POST /checkout/order-12347
...
```

The operation_name carries an entity identifier as a path segment.
Common with REST routers that don't template their paths in
instrumentation.

**Why ARIP encounters it:**

> Real OTel auto-instrumentation often reports the request path
> verbatim. Spring's `@RestController`, Express middleware, and many
> Go HTTP wrappers all do this by default. Templated path
> reconstruction is a separate concern most teams have not enabled.

**ARIP's previous behaviour:**

Observation-mode abstention fingerprint included up to 5 entry-point
operation names. Each unique path → unique fingerprint → singleton
cluster. 10 traces with the same shape produced 10 clusters. Digest
became unreadable under realistic noise.

**ARIP's current behaviour (post-validation fix):**

Abstention fingerprint = `(abstention_code, service_set)` only.
Operation_names are recorded on the cluster as a non-fingerprint
attribute. 10 path-parameter variants now collapse to one cluster.

**Verdict:**

- [x] Behaviour was misleading (singleton clusters), now correct
      (one cluster per honest pattern). Fix applied; documented in
      [PHASE_A_VALIDATION.md Appendix B](PHASE_A_VALIDATION.md).

**Catalogue test:** `tests/test_observation_realworld.py::test_jaeger_path_parameter_operation_name_clusters_safely`

---

### Pre-pilot P2 — Loki logs without resolvable trace_id

**First observed:** Phase A real-world validation, 2026-05-22
**Source:** synthetic Loki streams response with free-text "rate
limiter near threshold" line in a stream whose labels have no
trace_id and whose body is not JSON
**Affected layer:** operator-side adapter (`bin/loki-export-to-logs.py`)

**What the telemetry looks like:**

```text
stream labels: {"service_name":"payment-service","level":"warn"}
value:         "rate limiter near threshold"
```

No trace_id in labels. No JSON body to parse for a trace_id field.

**Why ARIP encounters it:**

> Many production log pipelines emit free-text application logs
> (especially older Java/log4j and Python `logging` modules without
> MDC propagation). Even when a service has OTel tracing, its logs
> may predate trace_id injection.

**ARIP's current behaviour:**

The adapter writes these logs to `--unmatched-out` rather than
silently attaching them to a random bundle. The observation
pipeline never sees them. Operators get a visible count of dropped
logs as adapter stderr output.

**Verdict:**

- [x] Behaviour is honest. Surfacing the unmatched count is the
      correct trust signal. No engine change needed.

**Catalogue test:** `tests/test_observation_realworld.py::test_loki_join_adds_logs_to_existing_bundles`

---

### Pre-pilot P3 — File rotation in place causes silent skip

**First observed:** Phase A real-world validation, 2026-05-22
**Source:** synthetic rotation simulation — full ingestion sets
cursor to end of file, file is replaced with shorter content under
the same path
**Affected layer:** `JsonlTraceSource` cursor semantics

**What the telemetry looks like:**

```text
bundles.jsonl       (cursor saved: 12345 bytes)
↓ operator rotates in place
bundles.jsonl       (now 200 bytes of fresh content)
```

**Why ARIP encounters it:**

> `logrotate` and equivalent tooling often truncate or replace files
> in place. Without inode tracking, a byte-offset cursor cannot
> distinguish a rotated file from a slowly-growing one.

**ARIP's current behaviour:**

The source seeks past EOF on the rotated file, reads nothing, and
saves the same cursor. New writes are not picked up until the cursor
exceeds the file size again, OR the source URI changes.

**Verdict:**

- [x] Behaviour is documented. Operator workflow in
      [INGESTION_GUIDE.md](INGESTION_GUIDE.md) prescribes "one source
      URI per rotation". Auto-detecting rotation introduces false-reset
      risk under concurrent writes; deferred until a pilot shows the
      docs workaround is insufficient.

**Catalogue test:** `tests/test_observation_realworld.py::test_file_rotation_does_not_silently_drop_new_writes`

---

### Pre-pilot P4 — Truncated gzip stream

**First observed:** Phase A real-world validation, 2026-05-22
**Source:** synthetic partial gzip (valid header, body chopped at 20
bytes)
**Affected layer:** `JsonlTraceSource` (gzip reading)

**What the telemetry looks like:**

A gzip file that decompresses partially before raising
`EOFError` / `BadGzipFile`.

**Why ARIP encounters it:**

> A writer that died mid-flush, a file copied while still being
> appended, or a network transfer that was interrupted.

**ARIP's current behaviour:**

The observation pipeline's per-trace try/except absorbs the gzip
exception, logs it, and advances the cursor. No traces from the
truncated portion are recorded. The store remains valid. The next
run on a complete file re-tries cleanly.

**Verdict:**

- [x] Behaviour is honest — partial data does not pollute the store,
      and the operator can re-run after the source is fixed.

**Catalogue test:** `tests/test_observation_realworld.py::test_partial_gzip_does_not_crash`
