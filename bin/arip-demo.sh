#!/usr/bin/env bash
# bin/arip-demo.sh — golden-path narrated demo.
#
# Walks a viewer through ARIP's full story in deterministic order:
#
#   A. healthy baseline       — the system works
#   B. webhook_race           — concurrent modification anomaly
#   C. pool_exhaustion        — DB connection pool saturation
#   D. retry_storm            — request amplification + retry exhaustion
#   E. generated RCA          — what one investigation report contains
#   F. cross-run fingerprint  — second run recognises repeat patterns
#
# One command. Reproducible. Sub-30 second runtime.
#
# Non-interactive (CI/screenshots):  ARIP_DEMO_NONINTERACTIVE=1 bin/arip-demo.sh
# Unattended e2e (no narration):     bin/arip-e2e.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAYWRIGHT_DIR="$REPO_ROOT/tests/playwright"
CORE_DIR="$REPO_ROOT/arip-core"
REPORT_DIR="$REPO_ROOT/reports"
PWREPORT="$PLAYWRIGHT_DIR/playwright-report.json"
MEMORY_DB="$REPO_ROOT/.arip/memory.db"
PR_COMMENT="$REPO_ROOT/arip-pr-comment.md"

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  CYAN=$(tput setaf 6); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); MAGENTA=$(tput setaf 5)
else
  BOLD=""; DIM=""; RESET=""; CYAN=""; GREEN=""; YELLOW=""; MAGENTA=""
fi

section() { echo; echo "${BOLD}${CYAN}══ $* ══${RESET}"; }
sub()     { echo; echo "${BOLD}${MAGENTA}── $* ──${RESET}"; }
note()    { echo "${DIM}$*${RESET}"; }
ok()      { echo "${GREEN}✓${RESET} $*"; }
warn()    { echo "${YELLOW}!${RESET} $*"; }
fatal()   { echo "${BOLD}${YELLOW}✗${RESET} $*" >&2; exit 1; }

# ─────── preflight + self-bootstrap ──────────────────────────────────

preflight() {
  command -v docker >/dev/null  || fatal "docker not on PATH. Install Docker Desktop or engine."
  command -v node   >/dev/null  || fatal "node not on PATH. Need Node 20+."
  command -v npm    >/dev/null  || fatal "npm not on PATH."
  command -v uv     >/dev/null  || fatal "uv not on PATH. Install via 'curl -LsSf https://astral.sh/uv/install.sh | sh'."
  command -v curl   >/dev/null  || fatal "curl not on PATH."
  command -v python3 >/dev/null || fatal "python3 not on PATH."

  local node_major
  node_major=$(node --version | sed 's/^v//' | cut -d. -f1)
  if [[ "$node_major" -lt 20 ]]; then
    fatal "Node $node_major detected; ARIP demo expects Node 20+."
  fi
  ok "preflight: docker, node $(node --version | tr -d v), npm, uv, curl, python3"
}

bootstrap_if_needed() {
  if [[ ! -d "$PLAYWRIGHT_DIR/node_modules" ]]; then
    note "Installing Playwright dependencies (one-time, ~5 s)…"
    ( cd "$PLAYWRIGHT_DIR" && npm install --no-audit --no-fund 2>&1 | tail -2 )
    ok "playwright deps installed"
  fi
  if [[ ! -d "$CORE_DIR/.venv" ]]; then
    note "Installing arip-core Python deps (one-time, ~15 s)…"
    ( cd "$CORE_DIR" && uv sync --extra dev 2>&1 | tail -2 )
    ok "arip-core deps installed"
  fi
}

press_enter() {
  if [[ "${ARIP_DEMO_NONINTERACTIVE:-}" == "1" ]]; then
    return
  fi
  echo
  read -r -p "${DIM}Press enter to continue…${RESET}" _ || true
}

# Pull a value out of a markdown report (line beginning with "- **<key>:**").
field_from_md() {
  local file="$1" key="$2"
  grep -m1 "^- \*\*${key}:\*\*" "$file" 2>/dev/null \
    | sed -E "s/^- \*\*${key}:\*\* *\\\?\`([^\\\`]+)\\\`?.*/\1/" \
    | sed 's/`//g'
}

# Find the latest markdown report matching a slug substring.
latest_report() {
  ls -t "$REPORT_DIR"/*"$1"*.md 2>/dev/null | head -1
}

# ─────────────────────────────────────────────────────────────────────

section "ARIP — golden demo path (6 stops)"
cat <<EOF
${DIM}You will see, in order:${RESET}

  ${BOLD}A.${RESET}  healthy baseline       — system works in the happy path
  ${BOLD}B.${RESET}  webhook_race           — concurrent modification of an order
  ${BOLD}C.${RESET}  pool_exhaustion        — DB connection pool saturation
  ${BOLD}D.${RESET}  retry_storm            — exponential retry amplification
  ${BOLD}E.${RESET}  one full RCA report    — what the engine actually writes
  ${BOLD}F.${RESET}  cross-run fingerprint  — "this pattern is repeating"

${DIM}One Playwright run produces all five test outcomes. ARIP investigates
each failure in turn. We narrate the results stop by stop.${RESET}
EOF
press_enter

# ─────────────────────────────────────────────────────────────────────

section "Step 0 — Preflight"
preflight
bootstrap_if_needed

section "Step 1 — Bring up the demo stack"
note "Services: payment-service, inventory-service, postgres, redis, jaeger, otel-collector."
( cd "$REPO_ROOT" && docker compose up -d 2>&1 | tail -8 )

for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/healthz >/dev/null \
     && curl -sf http://localhost:8081/healthz >/dev/null; then
    ok "services healthy on :8080 (payment) and :8081 (inventory)"
    break
  fi
  sleep 1
done

note "Resetting inventory stock so the demo is reproducible."
docker compose exec -T postgres psql -U arip -d arip -q -c \
  "INSERT INTO inventory (sku, stock) VALUES ('SKU-001', 100), ('SKU-002', 50), ('SKU-003', 0) \
   ON CONFLICT (sku) DO UPDATE SET stock = EXCLUDED.stock;" >/dev/null
ok "inventory reset (SKU-001=100, SKU-002=50, SKU-003=0)"

# Clean prior demo state so cross-run fingerprinting starts fresh.
rm -rf "$REPORT_DIR" "$REPO_ROOT/.arip" "$PR_COMMENT"

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Step 2 — Run the Playwright suite"
note "5 tests run in order:"
note "  1) baseline (passes)"
note "  2) inventory_error scenario (fails)"
note "  3) pool_exhaustion scenario  (fails)"
note "  4) retry_storm scenario      (fails)"
note "  5) webhook_race scenario     (fails)"
note ""
note "Each test annotates its trace_id + order_id so ARIP can correlate"
note "the failure with the right telemetry afterwards."
( cd "$PLAYWRIGHT_DIR" && rm -f playwright-report.json && npx playwright test 2>&1 | tail -10 || true )

if [[ ! -s "$PWREPORT" ]]; then
  warn "no Playwright report produced — aborting"
  exit 1
fi
ok "Playwright report written"

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Step 3 — Wait briefly for traces to flush"
note "The OTel Collector batches spans every ~5s. We wait so all spans"
note "(including the ~23 emitted in the retry-storm trace) are visible"
note "to the investigator before it queries Jaeger."
sleep 8
ok "ready"

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Step 4 — Run ARIP investigation (1st time)"
note "Pipeline: parse FailureEvents → fetch traces & logs → run 5"
note "deterministic rules → audit evidence → write reports/."
( cd "$CORE_DIR" && uv run arip investigate \
    "$PWREPORT" \
    --out "$REPORT_DIR" \
    --memory "$MEMORY_DB" \
    --environment "demo" )

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop A — Healthy baseline"
note "Before failures, prove the happy path works. Find the baseline trace:"
baseline_trace=$(python3 -c "
import json
d = json.load(open('$PWREPORT'))
def walk(suites):
    for s in suites:
        yield from s.get('specs', [])
        yield from walk(s.get('suites', []))
for spec in walk(d.get('suites', [])):
    if 'baseline' in spec.get('title', ''):
        for t in spec.get('tests', []):
            for a in t.get('annotations', []):
                if a.get('type') == 'trace_id':
                    print(a['description']); break
            break
        break
")
ok "baseline trace: ${baseline_trace:-<missing>}"
if [[ -n "${baseline_trace:-}" ]]; then
  note "→ http://localhost:16686/trace/${baseline_trace}"
fi
note ""
note "Because the baseline passed, ARIP did not generate a report for it."
note "Investigation only runs over FAILURES."

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop B — webhook_race  ·  concurrent_modification rule"
race_md=$(latest_report "order-transitions-stay-non-interleaved")
if [[ -n "$race_md" ]]; then
  note "Report: ${race_md#$REPO_ROOT/}"
  echo
  awk '/^## Primary hypothesis/,/^## [^P]/' "$race_md" | head -25
fi

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop C — pool_exhaustion  ·  db_pool_exhaustion rule"
pool_md=$(latest_report "checkout-latency-stays-within-sla")
if [[ -n "$pool_md" ]]; then
  note "Report: ${pool_md#$REPO_ROOT/}"
  echo
  awk '/^## Primary hypothesis/,/^## [^P]/' "$pool_md" | head -25
fi

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop D — retry_storm  ·  retry_storm rule"
retry_md=$(latest_report "checkout-succeeds-without-exhausting-retries")
if [[ -n "$retry_md" ]]; then
  note "Report: ${retry_md#$REPO_ROOT/}"
  echo
  awk '/^## Primary hypothesis/,/^## [^P]/' "$retry_md" | head -30
fi

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop E — what a full RCA report contains"
note "Open the retry_storm report and look at its structure end to end:"
note "  - TL;DR (deterministic, or LLM-paraphrased with API key)"
note "  - Failure block (test, trace, order, assertion, telemetry counts)"
note "  - Primary hypothesis: title, severity, confidence, rule_id"
note "    + description that explains the dynamic, not just the symptom"
note "    + suggested next step (specific, not 'investigate XYZ')"
note "    + Evidence: every cited span_id / log line exists in telemetry"
note "  - Alternative hypotheses (with their own evidence)"
note "  - Request timeline (cross-service, chronologically merged)"
note "  - Evidence index (clickable trace links)"

if [[ -n "$retry_md" ]]; then
  echo
  note "First 50 lines of the retry-storm report:"
  echo
  head -50 "$retry_md"
fi

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Step 5 — Render the GitHub PR comment"
note "This is the artifact the ARIP GitHub Actions workflow posts on a PR."
( cd "$CORE_DIR" && uv run arip pr-comment "$REPORT_DIR" --out "$PR_COMMENT" )
echo
head -20 "$PR_COMMENT"
echo "${DIM}… (full comment in $PR_COMMENT)${RESET}"

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Stop F — Cross-run fingerprinting (second run)"
note "We re-run the whole pipeline. The memory store from the first run"
note "is reused. Every fingerprint that appears again gets a"
note '"this same root-cause shape has been seen before" line in its report.'

( cd "$PLAYWRIGHT_DIR" && rm -f playwright-report.json && npx playwright test 2>&1 | tail -3 || true )
sleep 8
( cd "$CORE_DIR" && uv run arip investigate \
    "$PWREPORT" \
    --out "$REPORT_DIR" \
    --memory "$MEMORY_DB" \
    --environment "demo" )

press_enter

sub "Cross-run section from the latest retry_storm report"
retry_md2=$(latest_report "checkout-succeeds-without-exhausting-retries")
if [[ -n "$retry_md2" ]]; then
  # awk range "from ## Cross-run TO next heading" — second pattern
  # must NOT also match the first, so we anchor it on a different
  # leading character.
  awk '/^## Cross-run context/,/^## [^C]/' "$retry_md2" | sed '$d'
fi

echo
sub "Memory store contents"
note "Eight investigations across two runs, four distinct fingerprints:"
echo
sqlite3 -header -column "$MEMORY_DB" \
  "SELECT id, substr(test_name, 1, 38) AS test, primary_rule_id AS rule, fingerprint
     FROM investigations
   ORDER BY id"

press_enter

# ─────────────────────────────────────────────────────────────────────

section "Done"
report_count=$(ls "$REPORT_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
fp_count=$(sqlite3 "$MEMORY_DB" "SELECT COUNT(DISTINCT fingerprint) FROM investigations WHERE fingerprint IS NOT NULL")
inv_total=$(sqlite3 "$MEMORY_DB" "SELECT COUNT(*) FROM investigations")

cat <<EOF
${GREEN}What you just saw${RESET}

  • One Playwright suite produced 1 pass + 4 distinct failure modes.
  • ARIP investigated each failure deterministically:
        webhook_race      → ${BOLD}concurrent_modification${RESET}
        pool_exhaustion   → ${BOLD}db_pool_exhaustion${RESET}
        retry_storm       → ${BOLD}retry_storm${RESET}  (+ ${BOLD}downstream_error${RESET} alt)
        inventory_error   → ${BOLD}downstream_error${RESET}
  • Every claim cites real spans + real logs (audited).
  • The second run recognised repeat patterns via fingerprint.

EOF

sub "Generated outputs"
cat <<EOF
  ${BOLD}Investigation reports${RESET}     $report_count files in ${REPORT_DIR#$REPO_ROOT/}/
EOF
ls -1 "$REPORT_DIR"/*.md 2>/dev/null | sed "s|$REPO_ROOT/|    · |"
cat <<EOF

  ${BOLD}PR comment${RESET}                ${PR_COMMENT#$REPO_ROOT/}
  ${BOLD}Memory store (SQLite)${RESET}     ${MEMORY_DB#$REPO_ROOT/}
                            $inv_total investigations · $fp_count distinct fingerprints
EOF

sub "Fingerprint summary"
sqlite3 -header -column "$MEMORY_DB" \
  "SELECT primary_rule_id AS rule, fingerprint, COUNT(*) AS occurrences
     FROM investigations
    WHERE fingerprint IS NOT NULL
    GROUP BY fingerprint, primary_rule_id
    ORDER BY occurrences DESC, rule"

sub "Live URLs"
cat <<EOF
  ${BOLD}Jaeger UI${RESET}                 http://localhost:16686
EOF
# Print the per-failure direct Jaeger trace URLs so the user can click into each.
for f in "$REPORT_DIR"/*.md; do
  trace=$(grep -m1 '^- \*\*Trace:\*\* ' "$f" | sed -E 's/.*`([a-f0-9]+)`.*/\1/')
  rule=$(grep -m1 'Rule: ' "$f" | sed -E 's/.*`([^`]+)`.*/\1/')
  [[ -n "$trace" && -n "$rule" ]] && printf "  %-23s  http://localhost:16686/trace/%s  (%s)\n" "" "$trace" "$rule"
done

sub "CI artifact paths (mirrored from .github/workflows/arip-investigate.yml)"
cat <<EOF
  Artifact bundle name      ${BOLD}arip-reports${RESET}
  Bundle contents           reports/  ·  tests/playwright/playwright-report.json  ·  arip-pr-comment.md
  PR comment dedup key      header: arip-investigation (sticky-pull-request-comment@v2)
  Memory cache key          arip-memory-<repo>  (restore-keys: arip-memory-)
EOF

sub "Where to go next"
cat <<EOF
  Read first        docs/ARIP_DEMO_WALKTHROUGH.md
  Failure matrix    docs/FAILURE_MATRIX.md
  Rule registry     docs/INVESTIGATION_RULES.md
  Curated outputs   docs/examples/
  Roadmap           ROADMAP.md
  Stop the stack    docker compose down -v
EOF
