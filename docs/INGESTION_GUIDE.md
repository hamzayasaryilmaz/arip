# Ingestion guide — feeding `arip observe` real telemetry

Phase A's `arip observe` consumes JSONL trace bundles and directories
of JSON bundles. Real production telemetry rarely arrives in that
shape — it arrives as Jaeger search responses, Loki query streams,
GitHub Actions artifact zips, partitioned S3 archives, rotated log
files, and so on.

This guide is the operator-side bridge: how to convert each common
export shape into the JSONL trace-bundle format that the observation
pipeline already accepts, and the workflow patterns that survive
real-world ingestion pathologies (file rotation, partial gzip,
missing trace_ids in logs).

**Nothing in this guide adds engine capability.** The observation
module (`arip_core/observation/`) is unchanged. The adapters in
`bin/` are operator tooling — short, single-purpose, side-effect-free
Python scripts that you can read in full in 5 minutes each.

## Trace-bundle format (the target shape)

Every adapter below produces this shape, one bundle per JSONL line
(or one bundle per `.json` file in directory mode):

```json
{
  "trace_id": "abc...",
  "captured_at": "2026-05-20T10:23:00Z",
  "spans": [ /* span objects */ ],
  "logs":  [ /* log entries */ ]
}
```

Once you have a `.jsonl` or `.jsonl.gz` file (or a directory of
`.json` files) in this shape, observation is a single command:

```bash
uv run arip observe path/to/bundles.jsonl --store .arip/observation.db
```

## Workflow 1 — Jaeger JSON export

Jaeger's UI lets you download a search result as JSON. The
`/api/traces` HTTP endpoint emits the same shape:

```bash
# Pull a window's worth of traces from Jaeger
curl -s "$JAEGER/api/traces?service=payment-service&lookback=1h&limit=200" \
  > /tmp/jaeger-export.json

# Convert to trace bundles
python3 bin/jaeger-export-to-bundles.py \
  --in  /tmp/jaeger-export.json \
  --out /tmp/bundles.jsonl

# Observe
uv run arip observe /tmp/bundles.jsonl --store .arip/observation.db
```

The conversion handles Jaeger's typed-tag pathology (`int64`, `bool`,
`float64` tags get coerced to JSON-native values) and the
`processes` map (service-name lookup by `processID`).

Bundles produced by this path have **empty `logs`**. If you also have
correlated logs in Loki, follow Workflow 2 to join them in.

### Jaeger v2 `base_path` configuration (observed in op002 validation)

Some Jaeger v2 deployments configure a `base_path` in their
`jaeger_query` extension config. Then the HTTP API is under
`<base_path>/api/...` rather than `/api/...`. Example from the
OpenTelemetry Demo's bundled Jaeger config:

```yaml
extensions:
  jaeger_query:
    base_path: /jaeger/ui
```

So the trace search endpoint there is
`http://jaeger:16686/jaeger/ui/api/traces?service=...`.

How to detect: `curl http://<jaeger>/api/traces` returns the Jaeger
UI's HTML (the `<!doctype html>` line) instead of a JSON error.
That's the signal that the API has moved under a base_path. Inspect
the Jaeger config (`jaeger_query.base_path`) or the UI's network
panel to find it.

This is **not** a defect — it's a deliberate Jaeger v2 deployment
choice. The adapter accepts whatever JSON you feed it; you just
need to know which URL to curl.

## Workflow 2 — Loki log streams

```bash
# Pull the matching log window
logcli query '{service_name=~"payment-service|inventory-service"}' \
  --since=1h --output=json > /tmp/loki-export.json

# Join Loki logs onto existing trace bundles by trace_id
python3 bin/loki-export-to-logs.py \
  --in            /tmp/loki-export.json \
  --bundles       /tmp/bundles.jsonl \
  --out           /tmp/bundles-with-logs.jsonl \
  --unmatched-out /tmp/unmatched-logs.jsonl
```

`trace_id` resolution tries (in order):
1. The Loki stream's labels — if your collector tags streams with
   `trace_id`, this is the clean path.
2. The log line body, if it parses as JSON and contains a `trace_id`
   field — common with structured JSON loggers.

Free-text logs with no resolvable trace_id are written to
`--unmatched-out`. The adapter never silently absorbs them into a
random bundle — see Workflow pathology *"Loki logs without trace_id"*
below.

You can repoint the trace_id field name with `--trace-key` if your
convention differs (e.g. `--trace-key traceId`).

## Workflow 2.5 — Grafana Tempo (OTLP JSON)

**Important.** Tempo's `/api/traces/<trace_id>` endpoint does NOT
return Jaeger-compatible JSON. It returns OpenTelemetry's
protobuf-derived JSON shape (`batches` containing `resource` +
`scopeSpans` + `spans`, with base64-encoded IDs and OTLP attribute
wrappers). The Jaeger adapter does not work against this. Use the
Tempo-specific adapter instead:

```bash
# Tempo's search uses a different query model than Jaeger.
# Step 1: discover trace IDs in a window
curl -s "$TEMPO/api/search?tags=&limit=100" \
  | jq -r '.traces[].traceID' > /tmp/trace-ids.txt

# Step 2: bulk-fetch each trace's full response into one JSONL file
while read tid; do
  curl -sf "$TEMPO/api/traces/$tid"
  echo
done < /tmp/trace-ids.txt > /tmp/tempo-raw.jsonl

# Step 3: convert OTLP JSON → ARIP trace bundles
python3 bin/tempo-export-to-bundles.py \
  --in  /tmp/tempo-raw.jsonl \
  --out /tmp/bundles.jsonl

# Step 4: observe
uv run arip observe /tmp/bundles.jsonl --store .arip/observation.db
```

The Tempo adapter:
- Decodes base64-encoded `traceId` / `spanId` to hex
- Unwraps OTLP attribute value types (stringValue / intValue /
  boolValue / doubleValue)
- Maps OTLP status code 2 → "ERROR" and preserves the status message
- Extracts `service.name` from the resource attributes per batch
- Skips empty batches without crashing

What it does NOT handle (deferred until a real pilot needs it):
- Tempo's binary protobuf endpoint (`Accept: application/protobuf`).
  Use the JSON variant.
- Span events / logs inside spans (decoded as empty list — Tempo
  doesn't carry these on most production paths anyway; use Loki
  for application logs and join via Workflow 2).
- Tempo's TraceQL search syntax. The example above uses the
  simplest "all traces in window" search.

This adapter was added during op003 validation. See
[UNKNOWN_SYSTEMS_VALIDATION.md](UNKNOWN_SYSTEMS_VALIDATION.md)
"Defect 2" for the full discovery + fix narrative, and
[observe-pilot-archive/op003/](observe-pilot-archive/op003/) for
the captured digest and findings.

## Workflow 3 — GitHub Actions artifact

A CI run that uploads trace exports as an artifact:

```bash
# Download the artifact (e.g. via `gh run download`)
gh run download <run-id> -n traces -D /tmp/artifact

# Inspect the layout — common shapes:
#   /tmp/artifact/bundles.jsonl                  (Workflow 1 output)
#   /tmp/artifact/traces/*.json                  (one trace per file)
#   /tmp/artifact/traces/<date>/*.json           (partitioned)

# Single JSONL
uv run arip observe /tmp/artifact/bundles.jsonl

# Flat directory of JSON bundles
uv run arip observe /tmp/artifact/traces/

# Partitioned subdirectories — pass the recursive glob explicitly
uv run arip observe "dir:///tmp/artifact/traces" \
  --store .arip/observation.db
# (For deeply-nested layouts, run observe against each leaf
# directory separately so the cursor stays meaningful per source.)
```

The default `*.json` glob matches only the top level. If your
artifact partitions by date or hour, use one source per leaf
directory; observation maintains a separate cursor per source URI,
so cross-leaf state stays clean.

## Workflow 4 — Mixed directory of legacy formats

A directory of trace files in mixed shapes (some Jaeger native, some
already-converted bundles) is best processed in two passes:

```bash
# Convert Jaeger-shaped files first
for f in /tmp/legacy/jaeger-*.json; do
  python3 bin/jaeger-export-to-bundles.py --in "$f" \
    --out "/tmp/converted/$(basename "$f" .json).jsonl"
done

# Then concatenate into one stream
cat /tmp/converted/*.jsonl > /tmp/converted/all.jsonl
uv run arip observe /tmp/converted/all.jsonl
```

The observation cursor follows the byte offset of the single
combined file; appending more lines is safe, but the existing file
must not be rewritten in place.

## Workflow 5 — Rotated logs / archive directory

If you collect trace bundles into a rolling file with rotation
(`bundles.jsonl` → `bundles.jsonl.1.gz` → `bundles.jsonl.2.gz`…),
the safest pattern is **one source URI per file**:

```bash
# Each file gets its own cursor in observation state.
uv run arip observe /var/log/arip/bundles.jsonl.2.gz
uv run arip observe /var/log/arip/bundles.jsonl.1.gz
uv run arip observe /var/log/arip/bundles.jsonl
```

A current Phase A limitation, documented in
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md): if you rotate
in place (the same filename now points at a fresh, shorter file),
the saved cursor will be past the new file's EOF, and ARIP silently
skips the new content. Don't rotate in place. Use distinct URIs.

This is a deliberate design call. Auto-detecting rotation requires
the source to track file inode / size / mtime and reset the cursor
on shrinkage — features that introduce false-reset risk under
concurrent writes. For Phase A, the contract is: cursors are byte
offsets, the operator is responsible for source URI naming.

## Workflow 6 — S3 / object store snapshots

Treat S3 as a remote directory. Sync to local, then run the
directory adapter:

```bash
aws s3 sync s3://my-bucket/traces/2026-05-20/ /tmp/s3-traces/
uv run arip observe /tmp/s3-traces/
```

The directory cursor records the relative filename of the last
successfully emitted bundle, so re-syncing the bucket and re-running
picks up only new files.

## What can go wrong (pathology summary)

The exhaustive catalogue lives in
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md). The short
list — the things this guide's adapters and observation pipeline are
known to encounter:

| Pathology | Where surfaced | Operator action |
|---|---|---|
| Path-parameter operation names (`/checkout/order-12345`) | Cluster sample shows variants; fingerprint is stable post-fix | None — clustering already collapses these |
| Loki logs without `trace_id` | `--unmatched-out` file | Either fix the source instrumentation, or accept that abstention rate rises |
| Sampled-out parent span (orphan) | Quality `propagation_health` < 1.0; cluster lands in abstention | Note in pilot feedback; raise sample rate at the source if recurring |
| Path-parameter in path → cluster split (pre-fix) | Fixed: see [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md) Appendix B | None — fixed |
| Partial / truncated gzip | Per-trace try/except absorbs; cursor stays put for retry | Re-export the source, re-run |
| File rotation in place | Cursor past EOF, silent skip | Use unique source URIs per rotation |
| Mixed timezone / timestamp formats | Adapters coerce to ISO-8601 UTC | Verify output before observe |

## Operator pre-flight checklist

Before running `arip observe` against a new source:

1. **Source URI stable?** Will the file path or directory ever be
   rotated in place? If yes, plan rotation as fresh URIs.
2. **trace_id correlated?** Do logs carry a resolvable trace_id?
   If no, the `weak_evidence` abstention rate will be high.
3. **Storage path chosen?** `.arip/observation.db` is the default;
   pick a project-local path so per-project state stays separate.
4. **Budget sized to source?** `--budget 500` is the default. Large
   one-shot ingests can use `--budget 5000`; tail-style runs should
   stay small.
5. **`--min-recurrence` for noisy production?** The default is 1.
   For early pilots filter singletons with `--min-recurrence 5` to
   keep the digest readable.

## What the adapters DO NOT do

- They do NOT call out to Jaeger, Loki, S3, or any other backend.
  They read files you give them.
- They do NOT mutate or delete source files.
- They do NOT send anything to ARIP's investigation memory store.
  Observation has its own store (`obs_*` tables).
- They do NOT produce candidate tests, open PRs, page anyone, or
  perform any side effect beyond writing the output file you
  specified.

These constraints are part of Phase A's identity. See
[OBSERVE_MODE.md](OBSERVE_MODE.md) for the full no-drift contract.
