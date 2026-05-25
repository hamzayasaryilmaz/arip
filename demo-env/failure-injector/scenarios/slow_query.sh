#!/usr/bin/env bash
# slow_query: inventory-service sleeps 300ms before the DB update.
# Trace will complete successfully but with elevated db span latency.
set -euo pipefail
curl -sS -i -X POST http://localhost:8080/checkout \
  -H 'content-type: application/json' \
  -H 'X-Failure-Mode: slow_query' \
  -d '{"order_id":"ORD-SLOW","sku":"SKU-001","quantity":1}'
