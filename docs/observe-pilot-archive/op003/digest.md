# ARIP observation digest

_generated 2026-05-30T15:20:12.552256+00:00_

## Run summary

- source: `jsonl:///private/tmp/tempo-bundles.jsonl`
- traces observed: 30
- new events: 30
- idempotent skips: 0
- cursor: `∅` → `30874`
- quality band distribution: low=1, medium=29
- abstentions: no_rule_matched=30

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

These telemetry shapes recurred, but the engine could not nominate a primary hypothesis. Useful for telemetry-hygiene work, not for acting on the anomaly itself.

| abstention | recurrence | first seen | last seen | services | operations |
|---|---:|---|---|---|---|
| `no_rule_matched` | 29 | 2026-05-30 15:01 | 2026-05-30 15:12 | tempo-all | CAS, CAS loop, GET, LiveStore.cutOneInstanceToWal (+13) |
| `no_rule_matched` | 1 | 2026-05-30 15:01 | 2026-05-30 15:01 | tempo-vulture | vulture-13, vulture-46, vulture-55, vulture-71 (+3) |

## Low-quality observations

1 observation(s) in this window had a quality band of `low`. They are recorded for transparency but are NOT considered reliable enough to be acted on as patterns. Improving the telemetry hygiene gaps listed in each investigation's quality findings will let more of these become reasoning material.

## What this digest is NOT

- Not a list of confirmed root causes — every cluster is an
  evidence-aligned observation, not a verdict.
- Not a reproduction-candidate list — no test draft has been
  generated, no PR has been opened.
- Not an alerting surface — recurrence counts are descriptive,
  not thresholds for paging anyone.
- Not exhaustive — observation mode runs against whatever sources
  the operator pointed it at; absence here ≠ absence in reality.
