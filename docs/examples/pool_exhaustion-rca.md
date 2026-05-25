# Investigation Report — checkout latency stays within SLA under concurrent load (FAILS under pool_exhaustion)

_Generated at 2026-05-19T13:28:37.337454+00:00 in 0.04s_

## TL;DR

Database connection pool exhaustion in inventory-service. `inventory-service` exhausted its database connection pool. A `db.connection_hold` span waited 1499ms with the pool at 2/3 connections in use. The latency is **not** in the query — the query span itself is fast — it is in waiting for a free connection. This is the distinguishing signature of pool exhaustion vs. a slow query: pool-related signals on the acquire span, while the actual SQL stays normal. Next step: Either raise `MaxConns` for inventory-service, or shorten per-request connection-hold time. Look for long transactions, missing batching, or slow operations that check a connection out for the duration of a request rather than just the query.

## Cross-run context

This same root-cause shape has been seen **1** time(s) by ARIP (1 of them in the last 14 days) . Fingerprint: `cacda21ed02e005b`.

- First observed: 2026-05-19T13:28:10.701000+00:00
- Most recent:    2026-05-19T13:28:10.701000+00:00

## Flaky-test signal

❔ **unknown** — Only 2 prior runs recorded; need at least 5 to call flakiness. (100% fail rate over 2 runs)

## Failure

- **Test:** `checkout latency stays within SLA under concurrent load (FAILS under pool_exhaustion)`
- **Environment:** `demo`
- **When:** 2026-05-19T13:28:24.535000+00:00
- **Trace:** `432401b16400ea1663a4790fcfff12e2`
- **Order:** `ORD-POOL-1779197304556-1`
- **Assertion:** all 6 concurrent checkouts complete within 800ms
- **Telemetry:** db_queries=3, logs=5, spans=10, timeline_items=20

```
Error: 6/6 requests exceeded SLA 800ms (wall=3025ms). Slowest: 3024ms order=ORD-POOL-1779197304556-1 trace=432401b16400ea1663a4790fcfff12e2

expect(received).toBe(expected) // Object.is equality

Expected: 0
Received: 6
```

## Primary hypothesis

### Database connection pool exhaustion in inventory-service

- **Severity:** high  ·  **Confidence:** 0.93  ·  **Rule:** `db_pool_exhaustion`

`inventory-service` exhausted its database connection pool. A `db.connection_hold` span waited 1499ms with the pool at 2/3 connections in use. The latency is **not** in the query — the query span itself is fast — it is in waiting for a free connection. This is the distinguishing signature of pool exhaustion vs. a slow query: pool-related signals on the acquire span, while the actual SQL stays normal.

**Suggested next step:** Either raise `MaxConns` for inventory-service, or shorten per-request connection-hold time. Look for long transactions, missing batching, or slow operations that check a connection out for the duration of a request rather than just the query.

**Evidence:**

- `span` — `db.connection_hold` waited 1499ms for a connection; pool at 2/3 in-use (196 empty-acquires recorded since process start). · in `inventory-service` · [trace](http://localhost:16686/trace/432401b16400ea1663a4790fcfff12e2) · `{'db.pool.acquired': 2, 'db.pool.idle': 1, 'db.pool.max': 3, 'db.pool.total': 3, 'db.pool.empty_acquires_total': 196, 'db.pool.wait_ms': 1499}`
- `span` — `db.decrement_stock` itself only took 4.0ms — the database layer is healthy, the wait is at the pool. · in `inventory-service` · trace `432401b16400ea1663a4790fcfff12e2`
- `log` — inventory: slow db connection acquire · in `inventory` · trace `432401b16400ea1663a4790fcfff12e2` · `{'trace_id': '432401b16400ea1663a4790fcfff12e2', 'wait_ms': 1499, 'pool_acquired': 2, 'pool_max': 3}`

## Request timeline

```
13:28:24.566  span_start   [payment-service     ]  payment-service (3012.8ms)
13:28:24.566  span_start   [payment-service     ]  checkout.process (3012.8ms)
13:28:24.566  span_event   [payment-service     ]  span event: state.transition
13:28:24.566  span_start   [payment-service     ]  inventory.reserve_call (3012.6ms)
13:28:24.566  span_start   [payment-service     ]  inventory.reserve_attempt (3012.6ms)
13:28:24.566  span_start   [payment-service     ]  HTTP POST (3012.5ms)
13:28:24.567  log          [payment             ]  [INFO] order transition
13:28:24.568  span_start   [inventory-service   ]  inventory-service (3009.5ms)
13:28:24.568  span_start   [inventory-service   ]  inventory.handle_reserve (3009.5ms)
13:28:24.568  span_start   [inventory-service   ]  db.connection_hold (3002.2ms)
13:28:24.568  db_query     [inventory-service   ]  HOLD  (3002.2ms)
13:28:26.067  log          [inventory           ]  [WARN] slow db connection acquire
13:28:27.569  span_start   [inventory-service   ]  db.acquire_connection (7.2ms)
13:28:27.569  db_query     [inventory-service   ]  db.acquire_connection  (7.2ms)
13:28:27.573  span_start   [inventory-service   ]  db.decrement_stock (4.0ms)
13:28:27.573  db_query     [inventory-service   ]  UPDATE inventory (4.0ms)
13:28:27.577  log          [inventory           ]  [INFO] stock reserved
13:28:27.577  span_event   [payment-service     ]  span event: state.transition
13:28:27.578  log          [payment             ]  [INFO] order transition
13:28:27.578  log          [payment             ]  [INFO] checkout confirmed
```

## Evidence index

- http://localhost:16686/trace/432401b16400ea1663a4790fcfff12e2

