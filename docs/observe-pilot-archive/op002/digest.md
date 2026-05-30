# ARIP observation digest

_generated 2026-05-30T15:20:12.211913+00:00_

## Run summary

- source: `jsonl:///private/tmp/otel-traces/bundles.jsonl`
- traces observed: 291
- new events: 291
- idempotent skips: 0
- cursor: `∅` → `3508453`
- quality band distribution: medium=291
- abstentions: no_rule_matched=291

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

These telemetry shapes recurred, but the engine could not nominate a primary hypothesis. Useful for telemetry-hygiene work, not for acting on the anomaly itself.

| abstention | recurrence | first seen | last seen | services | operations |
|---|---:|---|---|---|---|
| `no_rule_matched` | 226 | 2026-05-30 15:01 | 2026-05-30 15:03 | ad, cart, currency, frontend, frontend-proxy, frontend-web (+5) | GET, GET /api/cart, GET /api/currency, GET /api/data (+16) |
| `no_rule_matched` | 42 | 2026-05-30 15:03 | 2026-05-30 15:03 | cart, currency, frontend, frontend-proxy, product-catalog, recommendation | GET, GET /api/cart, GET /api/currency, GET /api/products/[productId]/index (+16) |
| `no_rule_matched` | 10 | 2026-05-30 15:00 | 2026-05-30 15:03 | ad, cart, checkout, currency, email, frontend (+7) | GET, GET /api/data, GET /api/products/[productId]/index, GET /api/recommendations (+16) |
| `no_rule_matched` | 8 | 2026-05-30 15:03 | 2026-05-30 15:03 | currency, frontend, frontend-proxy, frontend-web, product-catalog | GET, GET /api/recommendations, astronomy-db, executing api route (pages) /api/recommendations (+5) |
| `no_rule_matched` | 2 | 2026-05-30 15:03 | 2026-05-30 15:03 | frontend, frontend-proxy, frontend-web, product-catalog, recommendation | GET, GET /api/recommendations, astronomy-db, executing api route (pages) /api/recommendations (+5) |
| `no_rule_matched` | 1 | 2026-05-30 15:03 | 2026-05-30 15:03 | currency, frontend, frontend-proxy, frontend-web, product-catalog, recommendation | GET, astronomy-db, get_product_list, oteldemo.CurrencyService/Convert (+4) |
| `no_rule_matched` | 1 | 2026-05-30 15:03 | 2026-05-30 15:03 | cart | POST, flagd.evaluation.v2.Service/ResolveBoolean |
| `no_rule_matched` | 1 | 2026-05-30 15:00 | 2026-05-30 15:00 | payment | dns.lookup |

## What this digest is NOT

- Not a list of confirmed root causes — every cluster is an
  evidence-aligned observation, not a verdict.
- Not a reproduction-candidate list — no test draft has been
  generated, no PR has been opened.
- Not an alerting surface — recurrence counts are descriptive,
  not thresholds for paging anyone.
- Not exhaustive — observation mode runs against whatever sources
  the operator pointed it at; absence here ≠ absence in reality.
