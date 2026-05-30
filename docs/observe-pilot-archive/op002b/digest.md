# ARIP observation digest

_generated 2026-05-30T15:36:20.516878+00:00_

## Run summary

- source: `jsonl:///private/tmp/otel-fi/bundles.jsonl`
- traces observed: 454
- new events: 454
- idempotent skips: 0
- cursor: `∅` → `4736494`
- quality band distribution: low=6, medium=448
- abstentions: no_rule_matched=451, weak_evidence=3

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

These telemetry shapes recurred, but the engine could not nominate a primary hypothesis. Useful for telemetry-hygiene work, not for acting on the anomaly itself.

| abstention | recurrence | first seen | last seen | services | operations |
|---|---:|---|---|---|---|
| `no_rule_matched` | 304 | 2026-05-30 15:32 | 2026-05-30 15:35 | ad, cart, currency, frontend, frontend-proxy, frontend-web (+5) | GET, GET /api/cart, GET /api/currency, GET /api/data (+16) |
| `no_rule_matched` | 72 | 2026-05-30 15:35 | 2026-05-30 15:35 | cart, currency, frontend, frontend-proxy, product-catalog, recommendation | GET, GET /api/cart, GET /api/currency, GET /api/products/index (+16) |
| `no_rule_matched` | 15 | 2026-05-30 15:35 | 2026-05-30 15:35 | cart | POST, POST /oteldemo.CartService/AddItem, POST /oteldemo.CartService/GetCart, flagd.evaluation.v2.Service/ResolveBoolean (+1) |
| `no_rule_matched` | 14 | 2026-05-30 15:35 | 2026-05-30 15:35 | recommendation | get_product_list, oteldemo.ProductCatalogService/ListProducts, oteldemo.RecommendationService/ListRecommendations |
| `no_rule_matched` | 14 | 2026-05-30 15:35 | 2026-05-30 15:35 | cart, frontend, frontend-proxy, frontend-web, product-catalog | GET, GET /api/cart, POST, POST /api/cart (+8) |
| `no_rule_matched` | 11 | 2026-05-30 15:33 | 2026-05-30 15:35 | ad, cart, checkout, currency, email, frontend (+7) | GET, GET /api/data, GET /api/products/[productId]/index, GET /api/recommendations (+16) |
| `no_rule_matched` | 6 | 2026-05-30 15:35 | 2026-05-30 15:35 | currency, frontend, frontend-proxy, product-catalog, recommendation | GET, GET /api/recommendations, astronomy-db, executing api route (pages) /api/recommendations (+6) |
| `no_rule_matched` | 3 | 2026-05-30 15:34 | 2026-05-30 15:35 | quote | POST /getquote, calculate-quote, {closure} |
| `no_rule_matched` | 3 | 2026-05-30 15:35 | 2026-05-30 15:35 | frontend | GET |
| `weak_evidence` | 3 | 2026-05-30 15:34 | 2026-05-30 15:35 | cart, checkout, currency, frontend, frontend-proxy, load-generator (+3) | POST, POST /api/checkout, POST /get-quote, POST /getquote (+4) |
| `no_rule_matched` | 2 | 2026-05-30 15:35 | 2026-05-30 15:35 | cart, frontend, frontend-proxy | GET, GET /api/cart, executing api route (pages) /api/cart, oteldemo.CartService/GetCart (+2) |
| `no_rule_matched` | 2 | 2026-05-30 15:34 | 2026-05-30 15:34 | ad | getAdsByCategory, oteldemo.AdService/GetAds |
| `no_rule_matched` | 1 | 2026-05-30 15:35 | 2026-05-30 15:35 | frontend-web, recommendation | GET, get_product_list, oteldemo.RecommendationService/ListRecommendations |
| `no_rule_matched` | 1 | 2026-05-30 15:35 | 2026-05-30 15:35 | frontend-proxy, quote | GET, POST /getquote, calculate-quote, {closure} |
| `no_rule_matched` | 1 | 2026-05-30 15:35 | 2026-05-30 15:35 | frontend, frontend-web | GET, GET /api/data, executing api route (pages) /api/data, oteldemo.AdService/GetAds |
| `no_rule_matched` | 1 | 2026-05-30 15:35 | 2026-05-30 15:35 | frontend, frontend-proxy, product-catalog | GET, GET /api/recommendations, astronomy-db, executing api route (pages) /api/recommendations (+3) |
| `no_rule_matched` | 1 | 2026-05-30 15:32 | 2026-05-30 15:32 | payment | dns.lookup |

## Low-quality observations

6 observation(s) in this window had a quality band of `low`. They are recorded for transparency but are NOT considered reliable enough to be acted on as patterns. Improving the telemetry hygiene gaps listed in each investigation's quality findings will let more of these become reasoning material.

## What this digest is NOT

- Not a list of confirmed root causes — every cluster is an
  evidence-aligned observation, not a verdict.
- Not a reproduction-candidate list — no test draft has been
  generated, no PR has been opened.
- Not an alerting surface — recurrence counts are descriptive,
  not thresholds for paging anyone.
- Not exhaustive — observation mode runs against whatever sources
  the operator pointed it at; absence here ≠ absence in reality.
