# ARIP observation digest

_generated 2026-05-25T23:16:56.008076+00:00_

## Run summary

- source: `jsonl:///private/tmp/hotrod-traces/bundles.jsonl`
- traces observed: 40
- new events: 40
- idempotent skips: 0
- cursor: `∅` → `1340656`
- quality band distribution: medium=40
- abstentions: no_rule_matched=40

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

These telemetry shapes recurred, but the engine could not nominate a primary hypothesis. Useful for telemetry-hygiene work, not for acting on the anomaly itself.

| abstention | recurrence | first seen | last seen | services | operations |
|---|---:|---|---|---|---|
| `no_rule_matched` | 40 | 2026-05-25 23:15 | 2026-05-25 23:15 | customer, driver, frontend, mysql, redis-manual, route | /customer, /dispatch, /route, FindDriverIDs (+4) |

## What this digest is NOT

- Not a list of confirmed root causes — every cluster is an
  evidence-aligned observation, not a verdict.
- Not a reproduction-candidate list — no test draft has been
  generated, no PR has been opened.
- Not an alerting surface — recurrence counts are descriptive,
  not thresholds for paging anyone.
- Not exhaustive — observation mode runs against whatever sources
  the operator pointed it at; absence here ≠ absence in reality.
