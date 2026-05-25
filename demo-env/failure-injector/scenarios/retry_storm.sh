#!/usr/bin/env bash
# retry_storm: inventory-service returns 503 (transient failure). The
# payment-service's production retry policy then kicks in and tries
# the inventory call up to 5 times with exponential backoff.
#
# Expected telemetry signature for the failing trace:
#   - inventory.reserve_call span (parent) with retry.* policy attrs
#   - 5x inventory.reserve_attempt spans (retry.attempt = 1..5)
#   - each with retry.backoff_ms = 0, 50, 100, 200, 400
#   - each with retry.reason = "upstream 503: service temporarily..."
#   - eventual HTTP 502 to client (retries exhausted)
set -euo pipefail

ORDER_ID="${ORDER_ID:-ORD-RETRY-$(date +%s)}"

now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

start=$(now_ms)
echo ">> issuing /checkout with retry_storm"
line=$(curl -sS -o /tmp/retry_body -D - -w "%{http_code}\n" \
  -X POST http://localhost:8080/checkout \
  -H 'content-type: application/json' \
  -H 'X-Failure-Mode: retry_storm' \
  -H 'X-Arip-Capture: true' \
  -d "{\"order_id\":\"$ORDER_ID\",\"sku\":\"SKU-001\",\"quantity\":1}" || true)
end=$(now_ms)
elapsed=$((end - start))

status=$(printf '%s' "$line" | tail -n 1)
trace_id=$(printf '%s' "$line" | grep -i '^x-trace-id:' | awk '{print $2}' | tr -d '\r')

echo "   status=$status  elapsed=${elapsed}ms  trace=${trace_id:-?}"
echo "   body=$(cat /tmp/retry_body)"
echo
echo ">> done. Jaeger UI: http://localhost:16686/trace/${trace_id:-}"
