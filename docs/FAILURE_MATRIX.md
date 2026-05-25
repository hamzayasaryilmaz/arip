# Failure Matrix

What pattern ARIP recognises in which trace shape, with what evidence,
and when it deliberately keeps silent.

This is the canonical mapping between **what can go wrong** in the
demo stack and **what the engine says about it**. Anything that does
not have a row here will not produce a hypothesis — by design.

## At a glance

| # | Scenario              | Primary rule              | Alternative rules    | Severity | Sample report                                                                |
|---|-----------------------|---------------------------|----------------------|----------|------------------------------------------------------------------------------|
| 1 | `slow_query`          | `latency_vs_db`           | —                    | medium   | (run the demo; not currently tested by a failing Playwright assertion)       |
| 2 | `inventory_error`     | `downstream_error`        | —                    | high     | [downstream_error-rca.md](examples/downstream_error-rca.md)                  |
| 3 | `webhook_race`        | `concurrent_modification` | `latency_vs_db`      | high     | [concurrent_modification-rca.md](examples/concurrent_modification-rca.md)    |
| 4 | `pool_exhaustion`     | `db_pool_exhaustion`      | —                    | high     | [pool_exhaustion-rca.md](examples/pool_exhaustion-rca.md)                    |
| 5 | `retry_storm`         | `retry_storm`             | `downstream_error`   | high     | [retry_storm-rca.md](examples/retry_storm-rca.md)                            |

## Detailed matrix

### 1 · `slow_query` — application-side latency

| Field                  | Value                                                                                          |
|------------------------|------------------------------------------------------------------------------------------------|
| Trigger                | `X-Failure-Mode: slow_query` header (`demo-env/failure-injector/scenarios/slow_query.sh`)      |
| What happens           | inventory-service sleeps 300 ms inside `inventory.handle_reserve` before any DB call           |
| Telemetry signature    | Handler span ≫ DB span (≥ 50 ms, ≥ 10× ratio); no pool attrs; no retry attrs; no error chain   |
| Primary rule           | `latency_vs_db`                                                                                |
| Alternative rules      | none                                                                                           |
| Deterministic evidence | handler span duration vs sum of child `db.*` durations; ratio attached to evidence text         |
| Confidence             | 0.85 (constant — single signal kind, no corroboration loop)                                    |
| Abstention if…         | handler span not present; or DB child span not present                                          |

### 2 · `inventory_error` — downstream 500

| Field                  | Value                                                                                          |
|------------------------|------------------------------------------------------------------------------------------------|
| Trigger                | `X-Failure-Mode: inventory_error` header                                                       |
| What happens           | inventory-service returns HTTP 500 with body `internal error`. Payment treats 500 as non-retriable, surfaces 502 |
| Telemetry signature    | One ERROR chain across services: `payment.HTTP POST` → `inventory.server` → 500. No retries, no pool, no DB span |
| Primary rule           | `downstream_error`                                                                             |
| Alternative rules      | none                                                                                           |
| Deterministic evidence | ERROR span pairs (parent ↔ child) where the services differ; HTTP status code attribute; inventory ERROR logs |
| Confidence             | 0.90                                                                                           |
| Abstention if…         | no cross-service ERROR pair exists; or only same-service errors                                |

### 3 · `webhook_race` — concurrent modification

| Field                  | Value                                                                                          |
|------------------------|------------------------------------------------------------------------------------------------|
| Trigger                | Playwright fires `/checkout` (slow) and `/webhook` in parallel for the same `order_id`         |
| What happens           | Two separate traces mutate the same order's `state.transition` events while overlapping in wall-clock time |
| Telemetry signature    | Two traces share `order.id` business key; their time windows overlap; each emits at least one `state.transition` span event; payment-service emits WARN log "order in unexpected state…" |
| Primary rule           | `concurrent_modification`                                                                      |
| Alternative rules      | `latency_vs_db` (slow_query was used to widen the race window — corroborating, not causal)     |
| Deterministic evidence | per-trace start/end timestamps; both `state.transition` events on the same `order.id`; WARN log line referencing the unexpected previous state |
| Confidence             | 0.60 → 0.92 depending on how many of (transitions, WARN log) are present                       |
| Abstention if…         | only one trace touches the `order.id`; or no time overlap; or only one side performed a transition (read-only on the other) |

### 4 · `pool_exhaustion` — DB connection pool saturation

| Field                  | Value                                                                                          |
|------------------------|------------------------------------------------------------------------------------------------|
| Trigger                | `X-Failure-Mode: pool_exhaustion` + concurrent requests (Playwright fires 6 in parallel)       |
| What happens           | Each request holds a pool connection while sleeping 1.5 s. With `POOL_MAX_CONNS=3`, late arrivals stall at `pool.Acquire` |
| Telemetry signature    | `db.acquire_connection` (or `db.connection_hold`) span carrying `db.pool.acquired ≥ db.pool.max` AND/OR `db.pool.wait_ms ≥ 100`; the actual `db.decrement_stock` UPDATE stays fast (~ 2 ms) — DB is healthy, pool is the bottleneck |
| Primary rule           | `db_pool_exhaustion`                                                                           |
| Alternative rules      | none (handler-to-DB ratio is ~1:1 so `latency_vs_db` does not fire)                            |
| Deterministic evidence | acquire span duration; verbatim `db.pool.*` attribute snippet; contrast span citing the fast actual UPDATE; WARN log "slow db connection acquire" |
| Confidence             | 0.80 → 0.95 depending on (empty_acquires_total > 0, healthy-query span present, WARN log present) |
| Abstention if…         | symptom looks similar (slow acquire) but `db.pool.*` attribute family is missing — rule does not speculate |

### 5 · `retry_storm` — request amplification

| Field                  | Value                                                                                          |
|------------------------|------------------------------------------------------------------------------------------------|
| Trigger                | `X-Failure-Mode: retry_storm` → inventory returns HTTP 503 (retriable). Payment's always-on exponential retry policy kicks in (5 attempts, 0/50/100/200/400 ms) |
| What happens           | 5× `inventory.reserve_attempt` spans in a single trace, all ERROR with the same `retry.reason`. Total wall-time spent retrying ≈ 750 ms. 5× downstream load amplification per logical request |
| Telemetry signature    | ≥ 2 spans in same trace + same operation, each carrying `retry.attempt`, `retry.backoff_ms`, `retry.reason`, `retry.policy`. Optional `retry.max_attempts`, `retry.attempts_used` on outer span. |
| Primary rule           | `retry_storm` (wins by confidence 0.94 vs `downstream_error` 0.90)                             |
| Alternative rules      | `downstream_error` — surfaced as a corroborating finding, since retries amplified a real downstream error |
| Deterministic evidence | each attempt span verbatim with `retry.*` attribute snippet; backoff sequence shown inline (`0ms→50ms→100ms→200ms→400ms`); downstream ERROR span identified as root cause; ERROR logs from each attempt |
| Confidence             | 0.80 → 0.95 depending on (consistent reason, exponential pattern, exhausted budget, ERROR logs) |
| Abstention if…         | retry metadata absent entirely (would degrade to `downstream_error`); or only one attempt visible (not a storm); or attempts on different operations (different chains) |

## Cross-cutting rules

Things the matrix above implies but doesn't repeat per row:

- **No rule cites a span that doesn't exist.** Every Evidence reference
  is audited against the actual telemetry; ungrounded references are
  dropped and confidence is decayed.
  (`arip-core/arip_core/engine/evidence_audit.py`)

- **No rule fires for a hypothesis with only one kind of evidence.**
  Primary hypotheses require at least 2 distinct evidence kinds
  (e.g. `{span, log}` or `{span, span_event}`). Otherwise the engine
  abstains via the `weak_evidence` pathway.
  (`arip-core/arip_core/engine/abstention.py`)

- **Cross-run intelligence is rule-independent.** Any hypothesis the
  engine emits gets a deterministic fingerprint computed from
  `rule_id + sorted(services) + sorted(evidence-kind multiset)`. The
  memory store joins on that fingerprint to surface
  "this same root-cause shape has been seen N time(s)".

- **Sampling never loses a row from this matrix.** OTel Collector
  policies always keep ERROR traces, slow traces, and traces marked
  with `arip.force_sample=true`. The demo's Playwright suite sets
  that header on every request so the fast OK side of webhook_race
  is also captured.

## Related

- [INVESTIGATION_RULES.md](INVESTIGATION_RULES.md) — rule source files and how to add one
- [FAILURE_SCENARIOS.md](FAILURE_SCENARIOS.md) — narrative description of each scenario
- [examples/](examples/) — curated real outputs you can read offline
