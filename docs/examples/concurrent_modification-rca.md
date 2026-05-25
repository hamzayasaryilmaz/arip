# Investigation Report — order transitions stay non-interleaved across traces

_Generated at 2026-05-19T13:28:37.415801+00:00 in 0.04s_

## TL;DR

Concurrent modification across `checkout.process` and `webhook.process`. Two separate traces mutated order `ORD-RACE-1779197308804` while overlapping in time by ~0ms. The longer operation `checkout.process` was already in flight when `webhook.process` ran end-to-end and changed the order's state. Neither side observed the other's transition before acting. This is a classic concurrent-modification pattern; the most common real-world instance is an asynchronous callback (webhook, event consumer) completing before the synchronous flow that initiated the underlying work. Next step: Establish a single authority for `ORD-RACE-1779197308804`'s state transitions (e.g. require `webhook.process` to wait for `checkout.process` to complete, or gate the transition on the expected previous state).

## Cross-run context

This same root-cause shape has been seen **1** time(s) by ARIP (1 of them in the last 14 days) . Fingerprint: `29cb8520c4f61051`.

- First observed: 2026-05-19T13:28:14.966000+00:00
- Most recent:    2026-05-19T13:28:14.966000+00:00

## Flaky-test signal

❔ **unknown** — Only 2 prior runs recorded; need at least 5 to call flakiness. (100% fail rate over 2 runs)

## Failure

- **Test:** `order transitions stay non-interleaved across traces`
- **Environment:** `demo`
- **When:** 2026-05-19T13:28:28.783000+00:00
- **Trace:** `5c8a7b3e0ac2418373c291c03a731c45`
- **Order:** `ORD-RACE-1779197308804`
- **Related traces:** `26e90da59a0fcf031140e6dc884d3a5d`
- **Assertion:** order history has no interleaved trace_ids
- **Telemetry:** db_queries=2, logs=7, spans=11, timeline_items=23

```
Error: transitions interleaved across traces. history=[{"at":"2026-05-19T13:28:28.810566126Z","status":"pending","trace_id":"5c8a7b3e0ac2418373c291c03a731c45","note":"checkout started"},{"at":"2026-05-19T13:28:28.857358626Z","status":"paid","trace_id":"26e90da59a0fcf031140e6dc884d3a5d","note":"payment webhook received"},{"at":"2026-05-19T13:28:29.116359877Z","status":"confirmed","trace_id":"5c8a7b3e0ac2418373c291c03a731c45","note":"inventory reserved"}]

expect(received).toBe(expected) // Object.is equality

Expected: 2
Received: 3
```

## Primary hypothesis

### Concurrent modification across `checkout.process` and `webhook.process`

- **Severity:** high  ·  **Confidence:** 0.92  ·  **Rule:** `concurrent_modification`

Two separate traces mutated order `ORD-RACE-1779197308804` while overlapping in time by ~0ms. The longer operation `checkout.process` was already in flight when `webhook.process` ran end-to-end and changed the order's state. Neither side observed the other's transition before acting. This is a classic concurrent-modification pattern; the most common real-world instance is an asynchronous callback (webhook, event consumer) completing before the synchronous flow that initiated the underlying work.

**Suggested next step:** Establish a single authority for `ORD-RACE-1779197308804`'s state transitions (e.g. require `webhook.process` to wait for `checkout.process` to complete, or gate the transition on the expected previous state).

**Evidence:**

- `span` — `checkout.process` ran 2026-05-19T13:28:28.810526+00:00 → 2026-05-19T13:28:29.116438+00:00 on order `ORD-RACE-1779197308804` · in `payment-service` · [trace](http://localhost:16686/trace/5c8a7b3e0ac2418373c291c03a731c45)
- `span` — `webhook.process` ran 2026-05-19T13:28:28.857335+00:00 → 2026-05-19T13:28:28.857431+00:00 (fully inside `checkout.process`'s window; ~0ms overlap) on order `ORD-RACE-1779197308804` · in `payment-service` · [trace](http://localhost:16686/trace/26e90da59a0fcf031140e6dc884d3a5d)
- `span_event` — state.transition pending → paid on order `ORD-RACE-1779197308804` at 2026-05-19T13:28:28.857361+00:00 · in `payment-service` · trace `26e90da59a0fcf031140e6dc884d3a5d`
- `span_event` — state.transition  → pending on order `ORD-RACE-1779197308804` at 2026-05-19T13:28:28.810567+00:00 · in `payment-service` · trace `5c8a7b3e0ac2418373c291c03a731c45`
- `span_event` — state.transition paid → confirmed on order `ORD-RACE-1779197308804` at 2026-05-19T13:28:29.116363+00:00 · in `payment-service` · trace `5c8a7b3e0ac2418373c291c03a731c45`
- `log` — payment: payment webhook applied to order not in confirmed state · in `payment` · trace `26e90da59a0fcf031140e6dc884d3a5d` · `{'order_id': 'ORD-RACE-1779197308804', 'trace_id': '26e90da59a0fcf031140e6dc884d3a5d', 'expected_previous': 'confirmed', 'actual_previous': 'pending'}`
- `log` — payment: order in unexpected state during confirmation · in `payment` · trace `5c8a7b3e0ac2418373c291c03a731c45` · `{'order_id': 'ORD-RACE-1779197308804', 'trace_id': '5c8a7b3e0ac2418373c291c03a731c45', 'expected_previous': 'pending', 'actual_previous': 'paid'}`

## Alternative hypotheses

### Latency above the database layer in inventory-service

- **Severity:** medium  ·  **Confidence:** 0.85  ·  **Rule:** `latency_vs_db`

`inventory.handle_reserve` is slow, but the DB work it performs is fast (305ms handler vs 2ms DB). The bottleneck is not in PostgreSQL — it is in the handler itself, before or after the DB call. Look for synchronous I/O, sleeps, blocking locks, or external calls.

**Suggested next step:** Profile the handler before and after the DB call. Look for synchronous I/O, sleeps, lock contention, or external calls.

**Evidence:**

- `span` — inventory-service.inventory.handle_reserve ran for 305.1ms but its DB work was only 2.1ms (~147× ratio). The latency is above the DB layer. · in `inventory-service` · [trace](http://localhost:16686/trace/5c8a7b3e0ac2418373c291c03a731c45)
- `span` — DB span `db.decrement_stock` took 0.9ms · in `inventory-service` · trace `5c8a7b3e0ac2418373c291c03a731c45`
- `span` — DB span `db.acquire_connection` took 1.2ms · in `inventory-service` · trace `5c8a7b3e0ac2418373c291c03a731c45`

## Request timeline

```
13:28:28.810  span_start   [payment-service     ]  payment-service (305.9ms)
13:28:28.810  span_start   [payment-service     ]  checkout.process (305.9ms)
13:28:28.810  span_event   [payment-service     ]  span event: state.transition
13:28:28.810  span_start   [payment-service     ]  inventory.reserve_call (305.7ms)
13:28:28.810  span_start   [payment-service     ]  inventory.reserve_attempt (305.7ms)
13:28:28.810  span_start   [payment-service     ]  HTTP POST (305.7ms)
13:28:28.810  log          [payment             ]  [INFO] order transition
13:28:28.810  span_start   [inventory-service   ]  inventory-service (305.2ms)
13:28:28.810  span_start   [inventory-service   ]  inventory.handle_reserve (305.1ms)
13:28:28.857  span_start   [payment-service     ]  payment-service (0.1ms)
13:28:28.857  span_start   [payment-service     ]  webhook.process (0.1ms)
13:28:28.857  span_event   [payment-service     ]  span event: state.transition
13:28:28.857  log          [payment             ]  [INFO] order transition
13:28:28.857  log          [payment             ]  [WARN] payment webhook applied to order not in confirmed state
13:28:29.114  span_start   [inventory-service   ]  db.acquire_connection (1.2ms)
13:28:29.114  db_query     [inventory-service   ]  db.acquire_connection  (1.2ms)
13:28:29.115  span_start   [inventory-service   ]  db.decrement_stock (0.9ms)
13:28:29.115  db_query     [inventory-service   ]  UPDATE inventory (0.9ms)
13:28:29.116  log          [inventory           ]  [INFO] stock reserved
13:28:29.116  span_event   [payment-service     ]  span event: state.transition
13:28:29.116  log          [payment             ]  [INFO] order transition
13:28:29.116  log          [payment             ]  [WARN] order in unexpected state during confirmation
13:28:29.116  log          [payment             ]  [INFO] checkout confirmed
```

## Evidence index

- http://localhost:16686/trace/26e90da59a0fcf031140e6dc884d3a5d
- http://localhost:16686/trace/5c8a7b3e0ac2418373c291c03a731c45

