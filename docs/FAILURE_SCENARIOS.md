# Failure Scenarios

Each scenario is deterministic and toggleable per-request. **The
application emits no special telemetry to identify which scenario is
running** — the only signals produced are the natural ones a real
failure of that class would produce. This is deliberate: the
investigation engine must derive its conclusions from honest
telemetry, not from labels the system under test thoughtfully
provides.

## Injection mechanism

Failures are injected via the `X-Failure-Mode` HTTP header. The
payment-service forwards the header to inventory-service transparently
but does NOT mirror it onto any span attribute. inventory-service
reads the header, performs the injected behaviour, and emits exactly
the telemetry that the corresponding real failure would emit.

| Scenario              | Header value         | Where it acts                |
|-----------------------|----------------------|------------------------------|
| Slow path             | `slow_query`         | inventory-service            |
| Internal failure      | `inventory_error`    | inventory-service            |
| Concurrent writes     | (none — parallel)    | payment-service              |
| Pool exhaustion       | `pool_exhaustion`    | inventory-service            |
| Retry storm           | `retry_storm`        | inventory-service (returns 503) → triggers payment retry loop |

## Scenarios

### `slow_query`

inventory-service sleeps for **300 ms** inside the
`inventory.handle_reserve` span before performing the DB UPDATE.

**Natural telemetry it produces** (no injection markers):
- `inventory.handle_reserve` span duration ≈ 305 ms
- `db.decrement_stock` child span duration ≈ 1–2 ms
- No errors, no special events
- A ~250× handler-vs-DB ratio is the only deviation from baseline

The `LatencyVsDBRule` finds this without knowing about injection.

**Reproduce:** `demo-env/failure-injector/scenarios/slow_query.sh`

### `inventory_error`

inventory-service returns HTTP 500 with body `internal error` and
emits a single `ERROR`-level log `"reserve failed"` with
`error=internal error`. No special attributes, no scenario name. This
is exactly what a real internal bug or a downed dependency would look
like.

**Natural telemetry it produces:**
- `inventory.handle_reserve` span has `status=ERROR`
- The server span has HTTP status 500
- Upstream `HTTP POST` and `checkout.process` spans are ERROR too
- One `ERROR` log line in inventory-service

The `DownstreamErrorRule` finds this by walking the span tree and
seeing the error chain bottom out in inventory.

**Reproduce:** `demo-env/failure-injector/scenarios/inventory_error.sh`

### `webhook_race` (driven by the test, not the application)

The (mock) payment processor's webhook arrives in parallel with a
slow checkout for the same `order_id`. The application has no idea
this is a race; it just emits its normal logs and state-transition
span events. Specifically:

- Each `state.transition` is an OTel span event with attributes
  `state.from`, `state.to`, `order.id` — the kind of event a real
  service would emit for an audit trail.
- When checkout finishes and finds the order already `paid`, it
  emits a WARN log `"order in unexpected state during confirmation"`
  with `expected_previous=pending, actual_previous=paid`.
- When the webhook arrives and finds the order not yet `confirmed`,
  it emits a WARN log
  `"payment webhook applied to order not in confirmed state"`.

These are honest, production-style signals. The `ConcurrentModification`
rule pieces the story together by finding:

1. Two traces sharing the same `order.id`
2. Their lifetimes overlap in wall-clock time
3. Each trace performs at least one `state.transition`
4. WARN logs corroborate that the application observed unexpected state

…and produces a `Concurrent modification of order X by A and B`
hypothesis, with the participating trace IDs, the timing overlap,
the transitions, and the WARN logs cited as evidence.

**Reproduce:** `demo-env/failure-injector/scenarios/webhook_race.sh`

### `pool_exhaustion`

A request in this mode checks a connection out of inventory-service's
PostgreSQL pool and **sleeps 1.5 s while holding it**. With
`POOL_MAX_CONNS=3` (set in `docker-compose.yml`) and N > 3 concurrent
requests, the pool saturates: late arrivals stall at `pool.Acquire`
until earlier holders release.

Production analogue: a slow transaction, a missing batch boundary, or
any code path that keeps a connection checked out across a slow
operation.

**Natural telemetry it produces:**
- `db.acquire_connection` span with elevated duration on victim
  requests — the wait happens here, not in the query
- `db.pool.acquired` ≈ `db.pool.max` at the moment of the slow span
  (pool saturated)
- `db.pool.wait_ms` reflects the time waited for a connection
- `db.pool.empty_acquires_total` increases (pool ran dry N times)
- `db.decrement_stock` span itself stays fast — the database is healthy
- WARN log `slow db connection acquire` with the pool snapshot

These are the standard attribute keys inventory-service emits and the
contract `PoolExhaustionRule` reads against. They do NOT advertise the
injection — the same shape is what a real saturated production pool
would produce.

**How the engine distinguishes from neighbours:**

| If you see…                                   | Rule that fires       |
|-----------------------------------------------|-----------------------|
| Slow handler, fast `db.*`, no pool stats      | `latency_vs_db`       |
| Slow `db.acquire_connection`, pool saturated  | `db_pool_exhaustion`  |
| ERROR chain across services, no DB activity   | `downstream_error`    |
| Two traces touching the same `order.id`       | `concurrent_modification` |

**Abstention contract:** if a span *looks* slow at the acquire layer
but the `db.pool.*` attributes are missing entirely, the rule
deliberately does not fire. The engine then surfaces the failure as
"no rule matched" rather than guessing.

**Reproduce:** `demo-env/failure-injector/scenarios/pool_exhaustion.sh`

### `retry_storm`

inventory-service returns HTTP 503 (`service temporarily unavailable`)
unconditionally. payment-service's **always-on** retry policy (5
attempts, exponential backoff: 0/50/100/200/400 ms) then fires.
All retries fail because the downstream stays unavailable, the client
sees HTTP 502 from payment-service.

This scenario is interesting because it exercises a production code
path (the retry loop) and shows what retry **amplification** looks
like in a trace: one logical user request fans out to N downstream
calls.

**Natural telemetry it produces:**
- Outer span `inventory.reserve_call` with retry **policy** metadata:
  `retry.policy=exponential`, `retry.max_attempts=5`,
  `retry.backoff_initial_ms=50`, `retry.backoff_multiplier=2`,
  `retry.attempts_used=5`
- N (=5) child spans `inventory.reserve_attempt`, each carrying
  per-attempt state: `retry.attempt=1..5`, `retry.backoff_ms`
  (the backoff applied **before** that attempt: 0/50/100/200/400),
  `retry.reason="upstream 503: service temporarily unavailable"`,
  `retry.retriable=true`, `retry.max_attempts=5`
- 5× downstream `inventory-service` server spans + `inventory.handle_reserve`,
  one per attempt, all ERROR
- 5× ERROR-level inventory logs ("reserve failed", error="service
  temporarily unavailable")
- Total trace duration ≈ sum(backoffs) + per-attempt overhead
  ≈ 750ms + a few ms

These keys are the stable contract `RetryStormRule` reads against.
The application does not advertise that this is the retry-storm
scenario — the exact same shape would come from any retriable
backend failure (rolling deploy, overloaded service, flaky DB
client).

**How the engine distinguishes from neighbours:**

| If you see…                                       | Rule that fires       |
|---------------------------------------------------|-----------------------|
| `retry.attempt` on 2+ same-op spans in one trace  | `retry_storm`         |
| `db.pool.*` saturated on an acquire span          | `db_pool_exhaustion`  |
| Single-attempt ERROR chain across services        | `downstream_error`    |
| Slow handler ≫ DB time, no pool, no retry metadata | `latency_vs_db`       |
| Two traces touching the same `order.id`           | `concurrent_modification` |

A retry-storm trace also triggers `downstream_error` (the failing
downstream is real), but `retry_storm` wins at scoring because it
has a more specific signature with higher confidence; the
downstream finding is surfaced as an alternative hypothesis.

**Abstention contract:** if attempts exist but `retry.*` metadata
is missing, the rule does NOT fire. Engine then surfaces "no rule
matched" rather than guessing.

**Reproduce:** `demo-env/failure-injector/scenarios/retry_storm.sh`

## Not yet implemented

The remaining scenarios will be added once the investigation engine
needs a new rule that requires them as test data:

- Connection pool exhaustion
- Retry storm (no circuit breaker)
- Stale cache (Redis)
- Async event drop (Kafka topic)
- Resource limit / OOMKilled (Kubernetes-only)
