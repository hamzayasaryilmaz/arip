#!/usr/bin/env bash
# End-to-end ARIP smoke test:
#   1) Ensure the demo stack is up
#   2) Run Playwright tests against it (expected to have failures)
#   3) Investigate the failures with `arip investigate`
#   4) Show the resulting Markdown reports
#
# Success criterion (per master prompt):
#   "Playwright testi fail olduğunda, sistem 60 saniye içinde otomatik
#    olarak kanıta dayalı bir root cause açıklaması üretiyorsa."
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAYWRIGHT_DIR="$REPO_ROOT/tests/playwright"
CORE_DIR="$REPO_ROOT/arip-core"
REPORT_DIR="$REPO_ROOT/reports"
PWREPORT="$PLAYWRIGHT_DIR/playwright-report.json"

echo ">> Ensuring demo stack is up"
( cd "$REPO_ROOT" && docker compose up -d 2>&1 | tail -5 )

echo ">> Waiting for services to be ready"
for i in {1..30}; do
  if curl -sf http://localhost:8080/healthz >/dev/null && \
     curl -sf http://localhost:8081/healthz >/dev/null; then
    echo "   services healthy"
    break
  fi
  sleep 1
done

echo ">> Resetting inventory stock (so successive runs are reproducible)"
docker compose exec -T postgres psql -U arip -d arip -q -c \
  "INSERT INTO inventory (sku, stock) VALUES ('SKU-001', 100), ('SKU-002', 50), ('SKU-003', 0) \
   ON CONFLICT (sku) DO UPDATE SET stock = EXCLUDED.stock;" >/dev/null

START=$(date +%s)

echo ">> Running Playwright tests (some are designed to fail)"
( cd "$PLAYWRIGHT_DIR" && rm -f playwright-report.json && npx playwright test 2>&1 | tail -8 || true )

if [[ ! -s "$PWREPORT" ]]; then
  echo "ERROR: no Playwright report produced at $PWREPORT" >&2
  exit 1
fi

echo ">> Waiting for traces to flush through OTel Collector"
# Margin: collector tail_sampling.decision_wait=5s + batch flush + jaeger ingest.
# Short OK traces (e.g. webhook side of webhook_race) need the full window.
sleep 8

echo ">> Running ARIP investigation"
MEMORY_DB="$REPO_ROOT/.arip/memory.db"
( cd "$CORE_DIR" && uv run arip investigate \
    "$PWREPORT" \
    --out "$REPORT_DIR" \
    --memory "$MEMORY_DB" \
    --environment "local" )

echo ">> Rendering PR-style comment"
( cd "$CORE_DIR" && uv run arip pr-comment "$REPORT_DIR" --out "$REPO_ROOT/arip-pr-comment.md" )

END=$(date +%s)
ELAPSED=$((END - START))

echo
echo ">> Pipeline complete in ${ELAPSED}s"
echo ">> Reports written to $REPORT_DIR/"
ls -la "$REPORT_DIR"
echo
echo ">> Success criterion: < 60s.  Result: ${ELAPSED}s  →  $([[ $ELAPSED -lt 60 ]] && echo PASS || echo FAIL)"
