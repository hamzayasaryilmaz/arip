# Investigation Report — checkout returns 200 OK (FAILS under inventory_error)

_Generated at 2026-05-19T13:28:37.296279+00:00 in 0.04s_

## TL;DR

Downstream inventory-service failure propagated upstream. The failing request bottomed out in inventory-service with: `HTTP 500`. Every span above it in the call stack is ERROR-tagged, which means inventory-service is the originating service. No span tree above inventory-service contributed a fault — the upstream services are just propagating the error. Next step: Inspect the inventory-service span in Jaeger and the inventory-service logs around the failure timestamp to identify the root error.

## Cross-run context

This same root-cause shape has been seen **1** time(s) by ARIP (1 of them in the last 14 days) . Fingerprint: `2db23e4e389cfa6b`.

- First observed: 2026-05-19T13:28:10.490000+00:00
- Most recent:    2026-05-19T13:28:10.490000+00:00

## Flaky-test signal

❔ **unknown** — Only 2 prior runs recorded; need at least 5 to call flakiness. (100% fail rate over 2 runs)

## Failure

- **Test:** `checkout returns 200 OK (FAILS under inventory_error)`
- **Environment:** `demo`
- **When:** 2026-05-19T13:28:24.329000+00:00
- **Trace:** `284dc1b6c70c671a1c1fc60c3970cd3a`
- **Order:** `ORD-INV-ERR-1779197304332`
- **Assertion:** checkout returns 200; received non-2xx
- **Telemetry:** db_queries=0, logs=4, spans=7, timeline_items=14

```
Error: expected 200 OK but got 502

expect(received).toBe(expected) // Object.is equality

Expected: 200
Received: 502
```

## Primary hypothesis

### Downstream inventory-service failure propagated upstream

- **Severity:** high  ·  **Confidence:** 0.90  ·  **Rule:** `downstream_error`

The failing request bottomed out in inventory-service with: `HTTP 500`. Every span above it in the call stack is ERROR-tagged, which means inventory-service is the originating service. No span tree above inventory-service contributed a fault — the upstream services are just propagating the error.

**Suggested next step:** Inspect the inventory-service span in Jaeger and the inventory-service logs around the failure timestamp to identify the root error.

**Evidence:**

- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/284dc1b6c70c671a1c1fc60c3970cd3a)
- `log` — inventory: reserve failed · in `inventory` · trace `284dc1b6c70c671a1c1fc60c3970cd3a` · `{'sku': 'SKU-001', 'order_id': 'ORD-INV-ERR-1779197304332', 'trace_id': '284dc1b6c70c671a1c1fc60c3970cd3a', 'error': 'internal error'}`

## Request timeline

```
13:28:24.333  span_start   [payment-service     ]  payment-service (0.6ms) ERROR
13:28:24.333  span_start   [payment-service     ]  checkout.process (0.6ms) ERROR
13:28:24.333  span_event   [payment-service     ]  span event: state.transition
13:28:24.333  span_start   [payment-service     ]  inventory.reserve_call (0.5ms)
13:28:24.333  span_start   [payment-service     ]  inventory.reserve_attempt (0.5ms) ERROR
13:28:24.333  span_start   [payment-service     ]  HTTP POST (0.4ms) ERROR
13:28:24.333  log          [payment             ]  [INFO] order transition
13:28:24.333  span_start   [inventory-service   ]  inventory-service (0.1ms) ERROR
13:28:24.333  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:24.334  log          [inventory           ]  [ERROR] reserve failed
13:28:24.334  span_event   [payment-service     ]  span event: state.transition
13:28:24.334  span_event   [payment-service     ]  span event: exception
13:28:24.334  log          [payment             ]  [INFO] order transition
13:28:24.334  log          [payment             ]  [ERROR] reserve failed
```

## Evidence index

- http://localhost:16686/trace/284dc1b6c70c671a1c1fc60c3970cd3a

