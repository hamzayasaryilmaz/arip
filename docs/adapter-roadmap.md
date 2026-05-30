# Adapter roadmap

What's currently supported, what's available on request, and what
the project intentionally won't pursue. This document is the
operator's authority on "do we have an adapter for X?".

## Currently shipped (ready to use)

| Backend | Adapter | Tested against | Status |
|---|---|---|---|
| **Jaeger** | `bin/jaeger-export-to-bundles.py` | Jaeger v1.x + v2.x (OTel Demo) | ✅ Production |
| **Tempo** | `bin/tempo-export-to-bundles.py` | Tempo v3.0 single-binary demo | ✅ Production |
| **Loki** | `bin/loki-export-to-logs.py` | Real Loki instance (op002c validation) | ✅ Production |
| **Elasticsearch** (traces) | `bin/elasticsearch-traces-to-bundles.py` | APM-shape + OTel-via-ES schemas | ✅ Production |
| **Elasticsearch** (logs) | `bin/elasticsearch-logs-to-bundles.py` | Same schemas | ✅ Production |
| **Honeycomb** | `bin/honeycomb-export-to-bundles.py` | Synthetic Honeycomb event fixtures | ✅ Production (live API path unverified) |
| **Grafana Cloud Tempo** | `bin/grafana-cloud-export-to-bundles.py` | Wraps Tempo adapter; auth path unverified | ⚠️ File mode verified, live API unverified |
| **AWS X-Ray** | `bin/aws-xray-to-bundles.py` | Synthetic X-Ray segment fixtures | ✅ Production (live AWS pull unverified) |
| **Directory of JSON bundles** | Built-in `JsonlTraceSource` / `DirectoryTraceSource` | — | ✅ Production |

"Production" here means: tested via unit fixtures + at least one
real validation pass against a real backend. "Unverified" means:
the wire-format conversion is correct (tested), but the live API
authentication / pagination path hasn't been hit against the
actual service yet.

## On-request adapters (build during paid pilot)

These adapters are **NOT shipped** but are well-understood —
typically 1-2 days of work as part of a paid pilot engagement
(see `docs/COMMERCIAL_OFFERINGS.md`). Sketches below for
operator orientation.

### Datadog APM

**Customer signal:** "We use Datadog for APM."

**Why not shipped:**
- Proprietary export API requires Datadog API key + app key
- No free testing tier with realistic span volume
- Datadog's tag system has subtle semantics differences from OTel
- Would need ongoing maintenance as Datadog evolves their API

**Build sketch:**
- Use Datadog's `GET /api/v1/spans` (Spans API)
- Auth via DD-API-KEY + DD-APPLICATION-KEY headers
- Pagination via `next_cursor` token
- Field mapping:
  ```
  trace_id    → trace_id (Datadog uses 64-bit; pad to 128-bit hex)
  span_id     → span_id
  parent_id   → parent_span_id
  service     → service_name
  resource    → operation_name (or "name" — vendor difference)
  start       → start_time (nanos → ISO)
  duration    → duration_us (nanos → us)
  error       → status (0=OK, 1=ERROR)
  meta        → attributes (flat dict already)
  ```
- Effort: ~6-8 hours to build + 4 hours to test against customer's
  real Datadog
- Billed: $2-3k as part of paid pilot

**Estimated rollout time:** 1.5 days during a paid pilot.

### New Relic APM

**Customer signal:** "We use New Relic for tracing."

**Build sketch:**
- Use NRDB via NerdGraph (GraphQL endpoint)
- Auth via API key + account ID
- Query: `SELECT * FROM Span WHERE traceId = '...'`
- Field mapping:
  ```
  trace.id        → trace_id
  guid            → span_id
  parent.id       → parent_span_id
  entity.name     → service_name
  name            → operation_name
  timestamp       → start_time (ms epoch)
  duration.ms     → duration_us (× 1000)
  http.status_code → drives status determination
  ```
- New Relic uses 32-character hex trace_id natively; no padding needed
- Effort: ~6-8 hours + 4 hours real-data testing
- Billed: $2-3k

### Splunk APM (formerly SignalFx)

**Customer signal:** "We use Splunk APM."

**Build sketch:**
- Use SignalFx Spans API (still the endpoint after rebrand)
- Auth via X-SF-Token header
- Field mapping similar to Datadog's
- Caveat: Splunk's span IDs are 16-char hex (64-bit); ARIP expects
  any length, no special handling needed
- Effort: ~5-6 hours + 3 hours real-data testing
- Billed: $2-3k

### Splunk Observability Cloud — logs

**Customer signal:** "We use Splunk Cloud for logs."

**Build sketch:**
- Use Splunk REST API (`/services/search/jobs`)
- Auth via session token
- Field mapping like ES logs adapter
- Caveat: Splunk's search jobs are async; need to create, poll, fetch
  (similar pattern to Honeycomb)
- Effort: ~6 hours
- Billed: $2-3k

### Dynatrace

**Customer signal:** "We use Dynatrace."

**Why this one is harder:**
Dynatrace's OneAgent does *deep* instrumentation that doesn't
cleanly map to OTel. PurePaths are not spans, they're a different
abstraction. The conversion is lossy.

**Build sketch:**
- Use Dynatrace API v2: `GET /api/v2/traces` (relatively new endpoint)
- Auth via API token with `traces.read` scope
- Conversion is lossy; warn operator about what's dropped
- Effort: 1-2 days (more uncertainty)
- Billed: $3-5k

### AppDynamics

**Customer signal:** "We use AppDynamics."

**Why this is the hardest:**
AppDynamics' data model is "Business Transactions" + "Snapshots"
— quite different from spans. Mapping is interpretive.

**Build sketch:**
- Use Controller API to pull BTs
- Each snapshot → ~1 trace bundle (approximate)
- Diagnostic data captured as attributes
- Warning: conversion fidelity is low; many AppD-specific concepts
  are dropped
- Effort: 2-3 days
- Billed: $4-6k
- **Honest recommendation:** if customer is on AppDynamics and
  considering ARIP, the better path is OTel migration. Ask first
  before building this adapter.

### Sumo Logic (logs)

**Customer signal:** "We use Sumo Logic for logs."

**Build sketch:**
- Use Sumo Search Job API (async like Splunk's)
- Auth via access ID + access key
- Field mapping similar to ES logs adapter
- Effort: ~5 hours
- Billed: $2k

### Logz.io

**Customer signal:** "We use Logz.io."

**Build sketch:**
- Logz.io is built on Elasticsearch — can reuse `elasticsearch-*`
  adapters with Logz.io's ES endpoint
- Auth via X-Api-Token header
- Effort: ~2 hours (mostly auth tweaks)
- Billed: $1k or bundled into integration engagement free

### Azure Application Insights

**Customer signal:** "We use Azure App Insights."

**Build sketch:**
- Use Application Insights REST API
- Auth via API key + app ID
- Field mapping:
  ```
  operation_Id  → trace_id
  id            → span_id
  parent_id     → parent_span_id
  cloud_RoleName → service_name
  name          → operation_name
  timestamp     → start_time
  duration      → duration_us (ms × 1000)
  success       → status (false → ERROR)
  customDimensions → attributes
  ```
- Effort: ~6 hours
- Billed: $2-3k

### GCP Cloud Trace

**Customer signal:** "We use GCP Cloud Trace."

**Build sketch:**
- GCP Cloud Trace is OTel-compatible via the OTel exporter
- Pull via `cloudtrace.projects.traces.list` REST API
- Auth via service account JSON
- OTel-shape spans; minimal conversion needed
- Effort: ~4 hours
- Billed: $1.5k

### AWS CloudWatch Logs

**Customer signal:** "Our logs are in CloudWatch."

**Build sketch:**
- Use CloudWatch Logs Insights query API
- Auth via AWS CLI / SigV4
- Caveat: CloudWatch doesn't auto-include trace_id; depends on
  logger configuration
- Effort: ~5 hours
- Billed: $2k

### Custom internal logging

**Customer signal:** "We have an internal log pipeline."

**Build sketch:**
- Depends entirely on customer's format
- Use the template: `bin/adapter-template.py`
- Operator + customer together identify field paths
- Effort: 4-8 hours depending on format complexity
- Billed: hourly at $200-300/hr OR fixed $2-3k bundled into pilot

## Explicitly NOT pursuing

These will not be built regardless of customer demand because they
violate project anti-goals (see `docs/POSITIONING.md`):

| "Adapter" request | Why declined |
|---|---|
| **Slack / Teams / Discord notification adapter** | ARIP is read-only; alerting is an anti-goal |
| **Jira / Linear ticket auto-creation** | Anti-goal — ARIP is not workflow automation |
| **PagerDuty / Opsgenie paging** | Same |
| **Auto-PR with suggested fix** | Anti-goal — that's Phase B/C/D candidate generation, trigger-gated |
| **Sentry adapter** | Sentry is error tracking, not distributed tracing — different category, doesn't fit the engine |
| **Datadog Logs Management → adapter that backfills missing trace_ids by ML** | ARIP doesn't invent telemetry — would violate trust contract |
| **CI/CD platform native plugins** (Jenkins plugin, CircleCI orb, etc.) | OSS Python script is sufficient; vendor-specific packaging is maintenance burden |
| **GUI / Web UI for any of the adapters** | Anti-goal #1 |
| **Hosted SaaS that runs adapters for the customer** | Anti-goal — no hosted control plane |

## How prioritization works

The order in which adapters get built is **driven by paid pilot
demand**, not by what's popular in the market.

Rule: a vendor adapter ships when a paid customer (Offering A or C)
needs it AND can provide:
1. Real telemetry samples for testing
2. Real environment access during the engagement
3. Permission for the adapter to be upstreamed (preferred but not required)

This rule exists because:
- Speculative adapters rot quickly as vendor APIs change
- Adapters built without real data have bugs that surface
  embarrassingly in the first real use
- "Supports X" claims that are actually "wire-format converter
  for X" without ever having hit a real X are deceptive

If 3+ customers ask for the same vendor adapter, that's a strong
enough signal to ship without waiting for a paid pilot. Until then:
**on-request only**.

## How to request an adapter

Two paths:

### As a paying customer
Mention it in the paid pilot SOW (Offering C). Adapter scoping is
$2-3k typical, baked into the engagement.

### As a community user (GitHub issue)
Open an issue with:
- Vendor name + version
- Realistic sample of the export format (10-20 spans)
- Authentication mechanism
- Field-to-OTel mapping (or "I don't know, please figure out")

If the request includes a usable fixture, a community contributor
or the maintainer may pick it up. Without a fixture, it sits in
the backlog.

## How to write an adapter yourself

See `docs/WRITING_AN_ADAPTER.md`. Start from `bin/adapter-template.py`.
Typical effort: 4-8 hours for a competent Python developer.

PRs welcome under the project's [CONTRIBUTING.md](../CONTRIBUTING.md)
discipline (tests required, no engine modifications, calibration
benchmark not weakened).

## Update cadence

This document is reviewed:
- After every successful paid pilot (add any new adapters built)
- Quarterly (re-assess priority based on community signal)
- When any anti-goal proposal surfaces (re-affirm or re-evaluate)

Last reviewed: 2026-05-30 (initial version)
