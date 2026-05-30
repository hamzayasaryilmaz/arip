# Usability findings — `op003` (Grafana Tempo, RUNNER's notes)

_Findings observed by the validation runner. No human operator
was present; these notes are about the **workflow itself**, not
about an operator's experience. See `feedback.md` for full
warm-up disclaimer._

Cross-system synthesis lives in
[docs/UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md).

## Finding 1 — Tempo's `/api/traces/<id>` is OTLP JSON, NOT Jaeger-compatible (CRITICAL → addressed via new adapter)

- **Observation:** Earlier docs (now deleted) suggested Tempo might
  be ingestible via the existing Jaeger adapter. False. Tempo's
  trace fetch API returns OpenTelemetry's protobuf-derived JSON:
  base64-encoded IDs, `*UnixNano` string timestamps, OTLP attribute
  value wrappers (`{"stringValue":"x"}` instead of Jaeger's typed
  tags), and a `batches`/`scopeSpans` shape instead of Jaeger's
  `data`/`processes`.
- **Where:** Tempo's HTTP API spec (and `bin/jaeger-export-to-bundles.py`
  silently failing because the input shape mismatches).
- **Severity:** **Critical** — claimed coverage was false.
- **Fix applied (this iteration):** New operator-side adapter
  [`bin/tempo-export-to-bundles.py`](../../../bin/tempo-export-to-bundles.py)
  handling base64 ID decoding, OTLP attribute unwrapping, status
  code mapping, and JSONL bulk input. 7 unit tests pinning the
  conversion behaviour
  ([tests/test_tempo_adapter.py](../../../arip-core/tests/test_tempo_adapter.py)).
- **Routing:**
  - [x] New `bin/` adapter (operator tooling, NOT a new engine capability)
  - [x] 7 unit tests
  - [x] INGESTION_GUIDE.md update — add Tempo workflow

## Finding 2 — Tempo search uses different query syntax (MINOR)

- **Observation:** Tempo's trace search is `?tags=&limit=N` (then
  fetch each trace individually via `/api/traces/<id>`).
  Jaeger's `?service=X&lookback=15m` doesn't exist on Tempo.
- **Severity:** Minor — different query model, mechanical to handle.
- **Proposed surface fix:** INGESTION_GUIDE.md to include the
  two-step recipe (search → bulk-fetch).
- **Routing:**
  - [x] INGESTION_GUIDE.md update

## Finding 3 — Tempo single-binary demo has no realistic application telemetry (REPORTING ONLY)

- **Observation:** Tempo single-binary demo emits only Tempo's
  internal control-plane traces + vulture's synthetic random
  traffic + k6-tracing's load-test output. There is no
  representative "application" emitting traces ARIP can reason
  about meaningfully.
- **Severity:** Cosmetic for ARIP validation — this is a Tempo
  demo limitation, not an ARIP issue.
- **Proposed action:** None for ARIP. The proper Tempo validation
  is to point a real application at Tempo and run the adapter
  against THAT application's traces. That's a separate test (would
  be op004 or later).

## Finding 4 — Port collision with OTel Demo's Prometheus (MINOR)

- **Observation:** Tempo demo's Prometheus tries to bind 9090,
  which collides with OTel Demo's Prometheus. The runner had to
  stop OTel Demo's stack before bringing up Tempo.
- **Severity:** Minor — Docker port collision, standard pattern.
- **Proposed surface fix:** Document in INGESTION_GUIDE.md that
  bringing up multiple OSS demos simultaneously requires manual
  port coordination.
- **Routing:**
  - [x] INGESTION_GUIDE.md note

## Findings explicitly NOT made

- **"Tempo's data was uninteresting"** — yes, but that's a Tempo
  demo property, not an ARIP issue. Documented as Finding 3
  rather than skipped silently.
- **"Could ARIP support Tempo's `/api/v2/traces/<id>` protobuf
  endpoint directly?"** — would be a new adapter feature; the
  JSON variant is the easier and more common operator path. Defer
  until a real operator with binary-protobuf-only Tempo pipeline
  surfaces.

## Summary

- Total findings: **4**
  - Critical: 1 (Finding 1, addressed)
  - Minor: 2 (Findings 2 + 4, INGESTION_GUIDE notes)
  - Cosmetic: 1 (Finding 3, no action)

Critical finding was addressed within the same iteration:
new adapter + 7 unit tests + cross-system synthesis doc. The
Tempo-native compatibility claim is now backed by tested code,
not by speculation.
