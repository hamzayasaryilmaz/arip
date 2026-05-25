#!/usr/bin/env bash
# webhook_race: fires the payment webhook in parallel with a slowed-down
# /checkout for the same order. Expected outcome: the order ends up in
# `paid_with_race` because the webhook applied PAID before /checkout had
# finished reserving inventory.
set -euo pipefail

ORDER_ID="${ORDER_ID:-ORD-RACE-$(date +%s)}"

# Kick off a slow checkout in the background so the webhook has time to
# arrive first. slow_query keeps the reservation pending ~300ms.
curl -sS -X POST http://localhost:8080/checkout \
  -H 'content-type: application/json' \
  -H 'X-Failure-Mode: slow_query' \
  -d "{\"order_id\":\"$ORDER_ID\",\"sku\":\"SKU-001\",\"quantity\":1}" \
  > /tmp/race-checkout.json &
CHECKOUT_PID=$!

# Brief delay so /checkout is in-flight, then fire the "early" webhook.
sleep 0.05
curl -sS -X POST http://localhost:8080/webhook \
  -H 'content-type: application/json' \
  -d "{\"order_id\":\"$ORDER_ID\"}" \
  > /tmp/race-webhook.json

wait "$CHECKOUT_PID"

echo '--- webhook response ---'
cat /tmp/race-webhook.json; echo
echo '--- checkout response ---'
cat /tmp/race-checkout.json; echo
echo '--- final order state ---'
curl -sS "http://localhost:8080/orders/$ORDER_ID"; echo
