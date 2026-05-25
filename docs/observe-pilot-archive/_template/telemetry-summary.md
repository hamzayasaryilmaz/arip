# Telemetry summary — `op<id>`

_What was ingested and what shape it was in. No PII. No verbatim
trace_ids or operation names that contain identifiers — those go
through scrubbing first._

## Source

- Backend kind:     `<jaeger | tempo | loki | grafana | gha-artifact | s3 | other>`
- Adapter used:     `<bin/jaeger-export-to-bundles.py | bin/loki-export-to-logs.py | direct jsonl | dir source>`
- Source command:   `<the literal command, with sensitive bits redacted>`
- Time window:      `<start … end (UTC), duration>`
- Bundle file size: `<bytes>`

## Ingestion outcome

- Traces ingested:           `<N>`
- New observation events:    `<N>`
- Idempotent skips:          `<N>`
- Unmatched Loki logs:       `<N>` (if applicable)
- Adapter warnings:          `<list, or "none">`

## Quality band distribution

| Band   | Count | Percentage |
|--------|------:|-----------:|
| high   |       |            |
| medium |       |            |
| low    |       |            |

## Per-rule match counts

| Rule | Matches |
|---|---:|
| `concurrent_modification` | |
| `retry_storm`             | |
| `downstream_error`        | |
| `db_pool_exhaustion`      | |
| `latency_vs_db`           | |

## Per-abstention counts

| Abstention code | Count |
|---|---:|
| `no_primary_trace`        | |
| `empty_telemetry`         | |
| `no_rule_matched`         | |
| `weak_evidence`           | |
| `conflicting_hypotheses`  | |

## Cluster counts in digest

- Rule-grounded clusters:      `<N>`
- Abstention-grounded clusters: `<N>`
- Total clusters:              `<N>`
- Total recurrence (sum across clusters): `<N>`

## Telemetry-hygiene findings

What was *missing* or *malformed* in this telemetry that affected
the digest. Pull from the engine's quality findings + your own
observations during ingestion.

- Missing `trace_id` propagation on `<service>`: `<N affected logs>`
- Orphan spans (parent not in slice): `<N affected traces>`
- Path-parameter operation names (e.g. `POST /checkout/<order_id>`):
  `<true | false; sample>`
- Other: `<list>`

If telemetry-hygiene issues dominated the run (digest is mostly
abstention clusters), this is a useful finding for the operator's
team — and a useful constraint on what conclusions to draw from
this pilot. Note it explicitly.
