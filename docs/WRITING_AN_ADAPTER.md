# Writing a new telemetry adapter

Adapters convert a telemetry backend's wire format into ARIP's
JSONL trace-bundle format. They live in `bin/` (operator tooling,
NOT part of `arip_core`) so they can be added without modifying
the engine.

This guide turns a new adapter into a 1-2 hour exercise. Six
adapters already follow this pattern; the seventh works the same.

## The contract

A trace bundle is one JSON object per line:

```json
{
  "trace_id": "abc123...",
  "captured_at": "2026-05-30T10:23:00Z",
  "spans": [ /* span objects */ ],
  "logs":  [ /* optional log entries */ ]
}
```

A span object:

```json
{
  "trace_id": "abc...",
  "span_id": "..",
  "parent_span_id": null,           // or a span_id
  "service_name": "frontend",
  "operation_name": "POST /checkout",
  "start_time": "2026-05-30T10:23:00.001Z",
  "duration_us": 12000,
  "status": "OK",                   // or "ERROR"
  "status_message": "",
  "attributes": {"http.status_code": 200},
  "events": []
}
```

That's the entire contract. If you can convert your backend's
trace data into this shape, your adapter works.

## Existing adapters as reference

| Backend | Adapter | Best to reference when adding... |
|---|---|---|
| Jaeger | `bin/jaeger-export-to-bundles.py` | Anything with Jaeger-derived JSON (Tempo via Jaeger compat, etc.) |
| Tempo | `bin/tempo-export-to-bundles.py` | OTLP JSON shape (base64 IDs, *UnixNano timestamps, OTLP attribute wrappers) |
| Loki | `bin/loki-export-to-logs.py` | Log adapters with stream + values shape |
| Elasticsearch traces | `bin/elasticsearch-traces-to-bundles.py` | Anything with configurable field mapping + flat/nested support |
| Elasticsearch logs | `bin/elasticsearch-logs-to-bundles.py` | Log adapters that need to join into bundles |
| Honeycomb | `bin/honeycomb-export-to-bundles.py` | Event-based stores |

If your backend resembles one of these closely, **copy that adapter
and modify**. The template (`bin/adapter-template.py`) is a clean
starting point with the structure but no specific backend logic.

## Step-by-step: writing a new adapter

### Step 0 — Understand the backend's wire format

Before writing a single line, answer:

1. How do I authenticate? (API key, basic auth, token, none)
2. What's the trace query endpoint? (URL pattern, parameters)
3. What's the response shape? (top-level keys, nested structure)
4. How are IDs encoded? (hex string, base64 bytes, integer)
5. How are timestamps encoded? (ISO string, epoch ms, epoch us, nanos)
6. How are attributes/tags structured? (flat dict, typed wrappers, key-value list)
7. How are status codes represented? (numeric, string enum, separate field)

If you can't answer all 7 from the backend's docs, you'll be
guessing. Get the answers first.

### Step 1 — Copy the template

```bash
cp bin/adapter-template.py bin/<vendor>-export-to-bundles.py
chmod +x bin/<vendor>-export-to-bundles.py
```

Replace the placeholders inside (look for `<VENDOR>` and `<TODO>`).

### Step 2 — Implement `_span_from_doc`

This is the only function you must write. It takes ONE
backend-shaped document (one span as the backend stores it) and
returns the JSONL-bundle span dict above.

Common transformations you'll need:

| Backend stores... | Convert to... |
|---|---|
| Base64-encoded ID | `base64.b64decode(s).hex()` |
| Hex-encoded ID | Pass through |
| Integer ID | Hex-format: `f"{n:016x}"` |
| ISO timestamp string | Pass through (or normalize to UTC) |
| Epoch milliseconds | `datetime.fromtimestamp(v/1000, tz=UTC).isoformat()` |
| Epoch microseconds | `datetime.fromtimestamp(v/1_000_000, ...)` |
| Epoch nanoseconds | `datetime.fromtimestamp(v/1_000_000_000, ...)` |
| Duration in ns | Divide by 1000 → us |
| Duration in ms | Multiply by 1000 → us |
| OTLP attribute wrappers (`{"stringValue": "x"}`) | Unwrap to `"x"` |
| Tag list with type info | `[{"key": "k", "value": v, "type": "..."}]` → `{"k": v}` |

### Step 3 — Implement `_hits_from_*` ingress

Two ingress paths supported by all adapters:

1. **`_hits_from_file`** — read from a local file (operator dumped
   the data via curl, vendor CLI, or backend export). Supports
   raw JSON, JSON array, or NDJSON.
2. **`_hits_from_<backend>`** — live query to the backend.
   Read-only, paginated, auth-configurable.

Copy from the closest existing adapter; the patterns are stable.

### Step 4 — Field mapping (configurable)

ARIP adapters make field paths configurable so an operator can
override defaults when their schema diverges:

```python
DEFAULT_TRACE_ID_FIELDS = ["trace_id", "trace.id", "traceID"]

p.add_argument("--trace-id-field",
               help=f"Default tries: {DEFAULT_TRACE_ID_FIELDS}")
```

This matters because every backend has subtle dialect differences
even when they all "support OpenTelemetry". Don't hard-code the
field path that worked for YOUR test data; let the operator
override.

### Step 5 — Group spans into trace bundles

ARIP's JSONL format is one BUNDLE per line, not one span per line.
Each bundle contains all spans sharing a trace_id. Adapters
typically:

```python
spans_by_trace: dict[str, list[dict]] = defaultdict(list)
for doc in docs:
    span = _span_from_doc(doc, cfg)
    if span:
        spans_by_trace[span["trace_id"]].append(span)

# Then write one bundle per trace_id
```

See `elasticsearch-traces-to-bundles.py` for the canonical pattern.

### Step 6 — Tests

Write tests in `arip-core/tests/test_<vendor>_adapter.py`. Use
realistic fixture documents (capture from the actual backend if
possible, otherwise synthesize from the backend's docs). Cover:

- Single trace, single span → one bundle
- Single trace, multiple spans → one bundle, multiple spans
- Multiple traces → multiple bundles
- ID format edge cases (base64, hex, etc.)
- Timestamp format edge cases
- Status code variants (OK / ERROR / numeric / string)
- Missing optional fields (degrade gracefully)
- Empty response (no crash, no bundles)
- Custom field mapping override works

Run `bin/<vendor>-export-to-bundles.py` via `subprocess` in tests
— exercises exactly what the operator invokes.

### Step 7 — Document in INGESTION_GUIDE.md

Add a `Workflow X.Y — <Vendor>` section to `docs/INGESTION_GUIDE.md`.
Show:

1. The `bash` command to query the backend
2. The adapter invocation
3. The `arip observe` invocation
4. Field-mapping override examples for common schema variants
5. Honest caveats (rate limits, auth, what's NOT supported)

### Step 8 — Add to README

In `README.md`'s "Pre-release validation" section, add:

```
- **<Vendor> adapter** — bin/<vendor>-export-to-bundles.py
```

## Adapter quality bar

Before merging:

- [ ] Tests pass (`uv run pytest tests/test_<vendor>_adapter.py`)
- [ ] Field mapping override actually works (test it)
- [ ] Handles missing optional fields gracefully (no crash)
- [ ] Documents what's NOT supported (rate limits, missing OTel
      features, vendor-specific quirks)
- [ ] INGESTION_GUIDE.md entry covers the operator workflow
- [ ] README.md lists the new adapter
- [ ] CHANGELOG.md entry under Unreleased
- [ ] Adapter exits non-zero if zero bundles were produced when
      input had documents (likely field mapping issue, warn loudly)

## What you should NOT do

- **Don't pretend to support things you can't test.** If you don't
  have access to the actual backend, don't merge the adapter as
  "production-ready". Mark it experimental.
- **Don't add backend-specific magic to the engine.** Adapters
  convert; the engine reasons over the JSONL contract. Never
  weaken the engine to accommodate a backend.
- **Don't depend on heavyweight vendor SDKs.** `httpx` for HTTP,
  stdlib for JSON, that's it. Adding `boto3` for AWS X-Ray would
  be a major dependency creep; use raw HTTP signed requests if
  needed.
- **Don't claim "supports X observability platform" when you only
  adapted the trace export.** Be specific: "supports Datadog APM
  trace export, NOT Datadog Logs Management"
- **Don't add an adapter speculatively.** Wait for a real
  customer (paid pilot) who uses that backend. Otherwise the
  adapter rots before anyone uses it.

## When to upstream vs keep custom

If you wrote an adapter for a paid pilot:

| Adapter is... | Upstream? |
|---|---|
| For a popular vendor (Datadog, NR, Splunk APM, Honeycomb) | Yes, with customer permission. Generalize the field mapping. |
| For a niche/internal vendor | Keep custom in customer's repo |
| Customer-specific config tweaks of an existing adapter | Definitely keep custom |
| New ID/timestamp format that's actually a standard | Upstream it via `_to_iso` / equivalent in shared helpers |

When upstreaming:
- Generalize field names (don't hard-code `customer-specific-field`)
- Add to INGESTION_GUIDE.md
- Add tests with synthetic fixtures (don't include real customer data)
- Credit the customer in CHANGELOG if they approved attribution

## Cross-references

- `bin/adapter-template.py` — clean starting point
- `bin/jaeger-export-to-bundles.py` — closest to "happy path"
- `bin/tempo-export-to-bundles.py` — closest to "messy ID/timestamp encoding"
- `bin/elasticsearch-traces-to-bundles.py` — closest to "configurable everything"
- [docs/INGESTION_GUIDE.md](INGESTION_GUIDE.md) — operator-side workflows
- [docs/POSITIONING.md](POSITIONING.md) — anti-goals; "broad connector ecosystem" is one
- [docs/COMMERCIAL_OFFERINGS.md](COMMERCIAL_OFFERINGS.md) — how new adapters are billed
