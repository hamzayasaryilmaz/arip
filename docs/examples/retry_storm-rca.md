# Investigation Report — checkout succeeds without exhausting retries (FAILS under retry_storm)

_Generated at 2026-05-19T13:28:37.377138+00:00 in 0.04s_

## TL;DR

Retry storm: 5 attempts to `inventory.reserve_attempt` in payment-service. `payment-service` issued 5 attempts of `inventory.reserve_attempt` against the same downstream in a single trace with exponential backoff (0ms→50ms→100ms→200ms→400ms). Total wall-time spent in the retry chain: 762ms. The amplification factor for this one logical request is 5× — under concurrent load, the downstream sees 5N calls for N user requests, which can push a marginally degraded service over the edge. The retry policy exhausted at 5/5; the client request failed because retries did not recover. Every attempt failed with the same reason (`upstream 503: service temporarily unavailable`), indicating a persistent downstream condition rather than a transient blip. Next step: Stabilise the downstream first: every retry hit the same failure, so adding more retries will not help. Once the downstream is fixed, reconsider the retry policy: 5 attempts with `exponential` backoff amplifies load by 5× during incidents and can prolong outages.

## Cross-run context

This same root-cause shape has been seen **1** time(s) by ARIP (1 of them in the last 14 days) . Fingerprint: `193713f185d4ac66`.

- First observed: 2026-05-19T13:28:13.960000+00:00
- Most recent:    2026-05-19T13:28:13.960000+00:00

## Flaky-test signal

❔ **unknown** — Only 2 prior runs recorded; need at least 5 to call flakiness. (100% fail rate over 2 runs)

## Failure

- **Test:** `checkout succeeds without exhausting retries (FAILS under retry_storm)`
- **Environment:** `demo`
- **When:** 2026-05-19T13:28:27.788000+00:00
- **Trace:** `320e0e4f8ebf8e3b65706cae1a5006a5`
- **Order:** `ORD-RETRY-1779197307809`
- **Assertion:** checkout returns 200 OK
- **Telemetry:** db_queries=0, logs=8, spans=23, timeline_items=34

```
Error: expected 200 OK; got 502 after retry policy ran

expect(received).toBe(expected) // Object.is equality

Expected: 200
Received: 502
```

## Primary hypothesis

### Retry storm: 5 attempts to `inventory.reserve_attempt` in payment-service

- **Severity:** high  ·  **Confidence:** 0.94  ·  **Rule:** `retry_storm`

`payment-service` issued 5 attempts of `inventory.reserve_attempt` against the same downstream in a single trace with exponential backoff (0ms→50ms→100ms→200ms→400ms). Total wall-time spent in the retry chain: 762ms. The amplification factor for this one logical request is 5× — under concurrent load, the downstream sees 5N calls for N user requests, which can push a marginally degraded service over the edge. The retry policy exhausted at 5/5; the client request failed because retries did not recover. Every attempt failed with the same reason (`upstream 503: service temporarily unavailable`), indicating a persistent downstream condition rather than a transient blip.

**Suggested next step:** Stabilise the downstream first: every retry hit the same failure, so adding more retries will not help. Once the downstream is fixed, reconsider the retry policy: 5 attempts with `exponential` backoff amplifies load by 5× during incidents and can prolong outages.

**Evidence:**

- `span` — `inventory.reserve_attempt` attempt 1/5 after 0ms backoff — ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5) · `{'retry.attempt': 1, 'retry.max_attempts': 5, 'retry.backoff_ms': 0, 'retry.policy': 'exponential', 'retry.reason': 'upstream 503: service temporarily unavailab`
- `span` — `inventory.reserve_attempt` attempt 2/5 after 50ms backoff — ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5) · `{'retry.attempt': 2, 'retry.max_attempts': 5, 'retry.backoff_ms': 50, 'retry.policy': 'exponential', 'retry.reason': 'upstream 503: service temporarily unavaila`
- `span` — `inventory.reserve_attempt` attempt 3/5 after 100ms backoff — ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5) · `{'retry.attempt': 3, 'retry.max_attempts': 5, 'retry.backoff_ms': 100, 'retry.policy': 'exponential', 'retry.reason': 'upstream 503: service temporarily unavail`
- `span` — `inventory.reserve_attempt` attempt 4/5 after 200ms backoff — ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5) · `{'retry.attempt': 4, 'retry.max_attempts': 5, 'retry.backoff_ms': 200, 'retry.policy': 'exponential', 'retry.reason': 'upstream 503: service temporarily unavail`
- `span` — `inventory.reserve_attempt` attempt 5/5 after 400ms backoff — ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5) · `{'retry.attempt': 5, 'retry.max_attempts': 5, 'retry.backoff_ms': 400, 'retry.policy': 'exponential', 'retry.reason': 'upstream 503: service temporarily unavail`
- `span` — Each attempt hit `inventory-service.inventory-service` ERROR: no message. The downstream was consistently failing — retries are the symptom, the downstream is the root cause. · in `inventory-service` · trace `320e0e4f8ebf8e3b65706cae1a5006a5`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — payment: reserve failed · in `payment` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'inventory reserve: exhausted 5 retries: inventory status 503: `

## Alternative hypotheses

### Downstream inventory-service failure propagated upstream

- **Severity:** high  ·  **Confidence:** 0.90  ·  **Rule:** `downstream_error`

The failing request bottomed out in inventory-service with: `HTTP 503`. Every span above it in the call stack is ERROR-tagged, which means inventory-service is the originating service. No span tree above inventory-service contributed a fault — the upstream services are just propagating the error.

**Suggested next step:** Inspect the inventory-service span in Jaeger and the inventory-service logs around the failure timestamp to identify the root error.

**Evidence:**

- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5)
- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5)
- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5)
- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5)
- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR · in `payment-service` · [trace](http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5)
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`
- `log` — inventory: reserve failed · in `inventory` · trace `320e0e4f8ebf8e3b65706cae1a5006a5` · `{'sku': 'SKU-001', 'order_id': 'ORD-RETRY-1779197307809', 'trace_id': '320e0e4f8ebf8e3b65706cae1a5006a5', 'error': 'service temporarily unavailable'}`

## Request timeline

```
13:28:27.815  span_start   [payment-service     ]  payment-service (762.4ms) ERROR
13:28:27.815  span_start   [payment-service     ]  checkout.process (762.4ms) ERROR
13:28:27.815  span_event   [payment-service     ]  span event: state.transition
13:28:27.815  span_start   [payment-service     ]  inventory.reserve_call (762.2ms) ERROR
13:28:27.815  span_start   [payment-service     ]  inventory.reserve_attempt (0.5ms) ERROR
13:28:27.815  span_start   [payment-service     ]  HTTP POST (0.5ms) ERROR
13:28:27.815  log          [payment             ]  [INFO] order transition
13:28:27.816  span_start   [inventory-service   ]  inventory-service (0.1ms) ERROR
13:28:27.816  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:27.816  log          [inventory           ]  [ERROR] reserve failed
13:28:27.870  span_start   [payment-service     ]  inventory.reserve_attempt (0.6ms) ERROR
13:28:27.870  span_start   [payment-service     ]  HTTP POST (0.5ms) ERROR
13:28:27.871  span_start   [inventory-service   ]  inventory-service (0.1ms) ERROR
13:28:27.871  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:27.871  log          [inventory           ]  [ERROR] reserve failed
13:28:27.973  span_start   [payment-service     ]  inventory.reserve_attempt (0.7ms) ERROR
13:28:27.973  span_start   [payment-service     ]  HTTP POST (0.6ms) ERROR
13:28:27.973  span_start   [inventory-service   ]  inventory-service (0.2ms) ERROR
13:28:27.973  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:27.973  log          [inventory           ]  [ERROR] reserve failed
13:28:28.175  span_start   [payment-service     ]  inventory.reserve_attempt (0.9ms) ERROR
13:28:28.176  span_start   [payment-service     ]  HTTP POST (0.7ms) ERROR
13:28:28.176  span_start   [inventory-service   ]  inventory-service (0.1ms) ERROR
13:28:28.176  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:28.176  log          [inventory           ]  [ERROR] reserve failed
13:28:28.577  span_start   [payment-service     ]  inventory.reserve_attempt (0.7ms) ERROR
13:28:28.577  span_start   [payment-service     ]  HTTP POST (0.5ms) ERROR
13:28:28.577  span_start   [inventory-service   ]  inventory-service (0.1ms) ERROR
13:28:28.577  span_start   [inventory-service   ]  inventory.handle_reserve (0.1ms)
13:28:28.577  log          [inventory           ]  [ERROR] reserve failed
13:28:28.577  span_event   [payment-service     ]  span event: state.transition
13:28:28.578  span_event   [payment-service     ]  span event: exception
13:28:28.578  log          [payment             ]  [INFO] order transition
13:28:28.578  log          [payment             ]  [ERROR] reserve failed
```

## Evidence index

- http://localhost:16686/trace/320e0e4f8ebf8e3b65706cae1a5006a5

