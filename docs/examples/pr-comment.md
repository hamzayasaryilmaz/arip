## 🔬 ARIP investigation

**4** failure(s) investigated

| Test | Finding | Sev | Conf | Flaky | Repeats |
|------|---------|-----|------|-------|---------|
| checkout latency stays within SLA under concurrent load (FA… | Database connection pool exhaustion in inventory-service | high | 0.93 | unknown | 0 |
| checkout returns 200 OK (FAILS under inventory_error) | Downstream inventory-service failure propagated upstream | high | 0.90 | unknown | 0 |
| checkout succeeds without exhausting retries (FAILS under r… | Retry storm: 5 attempts to `inventory.reserve_attempt` in p… | high | 0.94 | unknown | 0 |
| order transitions stay non-interleaved across traces | Concurrent modification across `checkout.process` and `webh… | high | 0.92 | unknown | 0 |

<details>
<summary><strong>1. checkout latency stays within SLA under concurrent load (FAILS under pool_exhaustion)</strong></summary>

**Database connection pool exhaustion in inventory-service** (severity `high`, confidence `0.93`, rule `db_pool_exhaustion`)

`inventory-service` exhausted its database connection pool. A `db.acquire_connection` span waited 1506ms with the pool at 3/3 connections in use. The latency is **not** in the query — the query span itself is fast — it is in waiting for a free connection. This is the distinguishing signature of pool exhaustion vs. a slow query: pool-related signals on the acquire span, while the actual SQL stays normal.

**Next step:** Either raise `MaxConns` for inventory-service, or shorten per-request connection-hold time. Look for long transactions, missing batching, or slow operations that check a connection out for the duration of a request rather than just the query.

**Evidence:**

- `span` — `db.acquire_connection` waited 1506ms for a connection; pool at 3/3 in-use (192 empty-acquires recorded since process start). — [trace](http://localhost:16686/trace/b298ab080700cabc25b052c76c6934fe)
- `span` — `db.decrement_stock` itself only took 2.6ms — the database layer is healthy, the wait is at the pool.
- `log` — inventory: slow db connection acquire

</details>

<details>
<summary><strong>2. checkout returns 200 OK (FAILS under inventory_error)</strong></summary>

**Downstream inventory-service failure propagated upstream** (severity `high`, confidence `0.90`, rule `downstream_error`)

The failing request bottomed out in inventory-service with: `HTTP 500`. Every span above it in the call stack is ERROR-tagged, which means inventory-service is the originating service. No span tree above inventory-service contributed a fault — the upstream services are just propagating the error.

**Next step:** Inspect the inventory-service span in Jaeger and the inventory-service logs around the failure timestamp to identify the root error.

**Evidence:**

- `span` — payment-service.HTTP POST ERROR caused by inventory-service.inventory-service ERROR — [trace](http://localhost:16686/trace/4fcc21977382990735599e5494fc9e61)
- `log` — inventory: reserve failed

</details>

<details>
<summary><strong>3. checkout succeeds without exhausting retries (FAILS under retry_storm)</strong></summary>

**Retry storm: 5 attempts to `inventory.reserve_attempt` in payment-service** (severity `high`, confidence `0.94`, rule `retry_storm`)

`payment-service` issued 5 attempts of `inventory.reserve_attempt` against the same downstream in a single trace with exponential backoff (0ms→50ms→100ms→200ms→400ms). Total wall-time spent in the retry chain: 767ms. The amplification factor for this one logical request is 5× — under concurrent load, the downstream sees 5N calls for N user requests, which can push a marginally degraded service over the edge. The retry policy exhausted at 5/5; the client request failed because retries did not recover. Every attempt failed with the same reason (`upstream 503: service temporarily unavailable`),…

**Next step:** Stabilise the downstream first: every retry hit the same failure, so adding more retries will not help. Once the downstream is fixed, reconsider the retry policy: 5 attempts with `exponential` backoff amplifies load by 5× during incidents and can prolong outages.

**Evidence:**

- `span` — `inventory.reserve_attempt` attempt 1/5 after 0ms backoff — ERROR — [trace](http://localhost:16686/trace/fed6be25fd32d6bac2594835c84b8377)
- `span` — `inventory.reserve_attempt` attempt 2/5 after 50ms backoff — ERROR — [trace](http://localhost:16686/trace/fed6be25fd32d6bac2594835c84b8377)
- `span` — `inventory.reserve_attempt` attempt 3/5 after 100ms backoff — ERROR — [trace](http://localhost:16686/trace/fed6be25fd32d6bac2594835c84b8377)
- `span` — `inventory.reserve_attempt` attempt 4/5 after 200ms backoff — ERROR — [trace](http://localhost:16686/trace/fed6be25fd32d6bac2594835c84b8377)
- `span` — `inventory.reserve_attempt` attempt 5/5 after 400ms backoff — ERROR — [trace](http://localhost:16686/trace/fed6be25fd32d6bac2594835c84b8377)
- _… 7 more_

</details>

<details>
<summary><strong>4. order transitions stay non-interleaved across traces</strong></summary>

**Concurrent modification across `checkout.process` and `webhook.process`** (severity `high`, confidence `0.92`, rule `concurrent_modification`)

Two separate traces mutated order `ORD-RACE-1779197294987` while overlapping in time by ~0ms. The longer operation `checkout.process` was already in flight when `webhook.process` ran end-to-end and changed the order's state. Neither side observed the other's transition before acting. This is a classic concurrent-modification pattern; the most common real-world instance is an asynchronous callback (webhook, event consumer) completing before the synchronous flow that initiated the underlying work.

**Next step:** Establish a single authority for `ORD-RACE-1779197294987`'s state transitions (e.g. require `webhook.process` to wait for `checkout.process` to complete, or gate the transition on the expected previous state).

**Evidence:**

- `span` — `checkout.process` ran 2026-05-19T13:28:14.993913+00:00 → 2026-05-19T13:28:15.296586+00:00 on order `ORD-RACE-1779197294987` — [trace](http://localhost:16686/trace/f9a74faa3f3444acc9782e12efbfb3d4)
- `span` — `webhook.process` ran 2026-05-19T13:28:15.040871+00:00 → 2026-05-19T13:28:15.040974+00:00 (fully inside `checkout.process`'s window; ~0ms overlap) on order `ORD-RACE-1779197294987` — [trace](http://localhost:16686/trace/94bb9d97a2a2733bb572d045e57c204f)
- `span_event` — state.transition pending → paid on order `ORD-RACE-1779197294987` at 2026-05-19T13:28:15.040904+00:00
- `span_event` — state.transition  → pending on order `ORD-RACE-1779197294987` at 2026-05-19T13:28:14.993953+00:00
- `span_event` — state.transition paid → confirmed on order `ORD-RACE-1779197294987` at 2026-05-19T13:28:15.296515+00:00
- _… 2 more_

</details>

