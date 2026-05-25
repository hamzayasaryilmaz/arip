#!/usr/bin/env bash
# inventory_error: inventory-service returns HTTP 500. payment-service
# maps this to 502 and marks the order `failed`.
set -euo pipefail
curl -sS -i -X POST http://localhost:8080/checkout \
  -H 'content-type: application/json' \
  -H 'X-Failure-Mode: inventory_error' \
  -d '{"order_id":"ORD-ERR","sku":"SKU-001","quantity":1}'
