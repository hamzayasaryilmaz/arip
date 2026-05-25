#!/usr/bin/env bash
# pool_exhaustion: fires N concurrent checkouts that each hold a DB
# connection while sleeping. With POOL_MAX_CONNS=3 (set in
# docker-compose.yml) and N > pool size, the latter requests are
# observably forced to wait at `db.acquire_connection`.
#
# Expected telemetry signature for the "victim" traces:
#   - inventory.handle_reserve span ~hold_duration + acquire_wait
#   - db.acquire_connection span with non-trivial duration
#   - db.pool.acquired ≈ db.pool.max  (pool saturated)
#   - db.pool.wait_ms = (large)
#   - WARN log "slow db connection acquire"
set -euo pipefail

N="${N:-6}"
SKU="${SKU:-SKU-001}"

now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

echo ">> firing $N concurrent /checkout requests with pool_exhaustion"
pids=()
for i in $(seq 1 "$N"); do
  ORDER_ID="ORD-POOL-$(date +%s)-$i"
  (
    start=$(now_ms)
    line=$(curl -sS -o /dev/null -D - -w "%{http_code}\n" \
      -X POST http://localhost:8080/checkout \
      -H 'content-type: application/json' \
      -H 'X-Failure-Mode: pool_exhaustion' \
      -H 'X-Arip-Capture: true' \
      -d "{\"order_id\":\"$ORDER_ID\",\"sku\":\"$SKU\",\"quantity\":1}" 2>/dev/null || true)
    end=$(now_ms)
    elapsed_ms=$((end - start))
    status=$(printf '%s' "$line" | tail -n 1)
    trace_id=$(printf '%s' "$line" | grep -i '^x-trace-id:' | awk '{print $2}' | tr -d '\r')
    printf "  req %-2d  status=%s  elapsed=%5sms  trace=%s  order=%s\n" "$i" "$status" "$elapsed_ms" "${trace_id:-?}" "$ORDER_ID"
  ) &
  pids+=($!)
done

for pid in "${pids[@]}"; do
  wait "$pid"
done

echo ">> done. Jaeger UI: http://localhost:16686"
