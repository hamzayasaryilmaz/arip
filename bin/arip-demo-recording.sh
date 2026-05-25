#!/usr/bin/env bash
# bin/arip-demo-recording.sh — recording-friendly demo runner.
#
# Differences vs bin/arip-demo.sh:
#   • Suppresses tooling noise (uv's VIRTUAL_ENV warning, etc.).
#   • Predictable pacing — explicit pauses between beats so a viewer
#     reading the screen can keep up.
#   • Section markers chosen to look clean in asciinema casts and
#     screen recordings (no overly-fancy unicode).
#   • Optional --asciinema flag wraps the whole run in `asciinema rec`
#     so you end up with arip-demo.cast for later replay/embedding.
#
# This script does NOT bypass the trust layer. The engine, the rules,
# the abstention pathway are unchanged. Only the surface presentation
# differs.
#
# Usage:
#   ./bin/arip-demo-recording.sh
#   ./bin/arip-demo-recording.sh --asciinema      # records to arip-demo.cast
#   ./bin/arip-demo-recording.sh --pace fast      # default pace=normal
#   ./bin/arip-demo-recording.sh --pace slow      # extra time per beat for video
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAYWRIGHT_DIR="$REPO_ROOT/tests/playwright"
CORE_DIR="$REPO_ROOT/arip-core"
REPORT_DIR="$REPO_ROOT/reports"
PWREPORT="$PLAYWRIGHT_DIR/playwright-report.json"
MEMORY_DB="$REPO_ROOT/.arip/memory.db"
PR_COMMENT="$REPO_ROOT/arip-pr-comment.md"

# Suppress uv's "VIRTUAL_ENV doesn't match the project's .venv" warning.
# It appears on every uv run when the host shell has VIRTUAL_ENV set to
# something else (e.g. macOS Xcode bundled Python). It is noise in a
# recording.
unset VIRTUAL_ENV

# ── Args ──────────────────────────────────────────────────────────────

PACE=normal
ASCIINEMA=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --asciinema) ASCIINEMA=1; shift ;;
    --pace)      PACE="$2";    shift 2 ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | head -n -1 | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

case "$PACE" in
  fast)   BEAT_PAUSE=1 ;;
  normal) BEAT_PAUSE=3 ;;
  slow)   BEAT_PAUSE=5 ;;
  *) echo "pace must be one of: fast, normal, slow" >&2; exit 2 ;;
esac

# ── Asciinema wrapper ────────────────────────────────────────────────

if [[ "$ASCIINEMA" == "1" ]]; then
  if ! command -v asciinema >/dev/null 2>&1; then
    echo "asciinema is not installed. Install with 'brew install asciinema' (mac) or pip install asciinema."
    exit 1
  fi
  CAST="$REPO_ROOT/arip-demo.cast"
  echo ">> Recording to $CAST"
  exec asciinema rec \
       --command "ARIP_DEMO_RECORDING_INNER=1 PACE=$PACE bash $0" \
       --title "ARIP investigation demo" \
       --idle-time-limit 2 \
       "$CAST"
fi

# ── Terminal helpers (asciinema-friendly: no fancy box-drawing) ──────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  CYAN=$(tput setaf 6); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); MAGENTA=$(tput setaf 5)
else
  BOLD=""; DIM=""; RESET=""; CYAN=""; GREEN=""; YELLOW=""; MAGENTA=""
fi

beat()     { echo; echo "${BOLD}${CYAN}── $* ──${RESET}"; sleep "$BEAT_PAUSE"; }
moment()   { echo "${BOLD}${MAGENTA}★ $* ★${RESET}"; }
note()     { echo "${DIM}$*${RESET}"; }
ok()       { echo "${GREEN}✓${RESET} $*"; }
warn()     { echo "${YELLOW}!${RESET} $*"; }
fatal()    { echo "${BOLD}${YELLOW}✗${RESET} $* — aborting." >&2; exit 1; }
pause_for_viewer() { sleep "$BEAT_PAUSE"; }

# Run uv silently — drop stderr noise that's purely tool diagnostics.
uv_quiet() {
  ( cd "$CORE_DIR" && uv "$@" 2>&1 \
      | grep -vE 'warning:.*VIRTUAL_ENV' \
      | grep -vE 'does not match the project environment' || true )
}

# ── Beat 0: framing ──────────────────────────────────────────────────

clear || true
cat <<EOF
${BOLD}ARIP investigation demo — recording mode${RESET}

  ${DIM}Deterministic, trust-aware investigation engine.${RESET}
  ${DIM}Five rules. Evidence-grounded. Honest abstention.${RESET}
  ${DIM}No LLM in the analysis path. No marketing language in this terminal.${RESET}

  Pace: ${BOLD}${PACE}${RESET}  ·  pause-per-beat: ${BEAT_PAUSE}s
EOF
pause_for_viewer

# ── Beat 1: bring up the stack ───────────────────────────────────────

beat "1. Bring up the local demo stack (Docker Compose)"
note "Six services: payment-service, inventory-service, postgres, redis,"
note "jaeger, otel-collector. The OTel collector enforces tail sampling."
( cd "$REPO_ROOT" && docker compose up -d 2>&1 | tail -5 )

for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/healthz >/dev/null \
     && curl -sf http://localhost:8081/healthz >/dev/null; then
    ok "services healthy on :8080 (payment) and :8081 (inventory)"
    break
  fi
  sleep 1
done

note "Resetting inventory to baseline state for a reproducible run."
docker compose exec -T postgres psql -U arip -d arip -q -c \
  "INSERT INTO inventory (sku, stock) VALUES ('SKU-001', 100), ('SKU-002', 50), ('SKU-003', 0) \
   ON CONFLICT (sku) DO UPDATE SET stock = EXCLUDED.stock;" >/dev/null
ok "inventory state reset"

rm -rf "$REPORT_DIR" "$REPO_ROOT/.arip" "$PR_COMMENT"
ok "previous run artifacts cleared"

pause_for_viewer

# ── Beat 2: Playwright produces failures ─────────────────────────────

beat "2. Run the Playwright suite — five tests, four designed to fail"
note "Each failing test annotates its trace_id + order_id so ARIP can"
note "correlate the failure with the right telemetry."
( cd "$PLAYWRIGHT_DIR" && rm -f playwright-report.json && npx playwright test 2>&1 | tail -8 || true )

if [[ ! -s "$PWREPORT" ]]; then
  fatal "no Playwright report produced"
fi
ok "Playwright JSON report written"

pause_for_viewer

# ── Beat 3: wait for trace flush ─────────────────────────────────────

beat "3. Wait for the OTel Collector to flush traces"
note "Tail sampling decision window is 5s. Wait 8s for safety;"
note "this is the 'sample-but-don't-drop-errors' policy doing its job."
sleep 8
ok "ready"

# ── Beat 4: investigation ────────────────────────────────────────────

beat "4. ARIP runs the investigation pipeline"
moment "DEMO MOMENT — watch the four primary hypotheses, one per failure"
note "Pipeline: parse → correlate → audit evidence → run 5 rules →"
note "abstain or rank → render markdown + PR comment + memory store."
uv_quiet run arip investigate \
    "$PWREPORT" \
    --out "$REPORT_DIR" \
    --memory "$MEMORY_DB" \
    --environment "demo"

pause_for_viewer

# ── Beat 5: tour the per-failure reports ─────────────────────────────

beat "5. Tour one full investigation report"
moment "DEMO MOMENT — evidence-grounded RCA, no LLM in the analysis"

retry_md=$(ls -t "$REPORT_DIR"/checkout-succeeds-without-exhausting-retries-*.md 2>/dev/null | head -1)
if [[ -n "$retry_md" ]]; then
  echo "${DIM}${retry_md#$REPO_ROOT/}${RESET}"
  echo
  awk '/^## Primary hypothesis/,/^## [^P]/' "$retry_md" | head -28
fi
pause_for_viewer

# ── Beat 6: PR comment ───────────────────────────────────────────────

beat "6. Render the GitHub-style sticky PR comment"
moment "DEMO MOMENT — this is what ARIP posts on a real PR"
uv_quiet run arip pr-comment "$REPORT_DIR" --out "$PR_COMMENT"
head -22 "$PR_COMMENT"
echo "${DIM}... full comment continues in $PR_COMMENT${RESET}"

pause_for_viewer

# ── Beat 7: cross-run fingerprinting ─────────────────────────────────

beat "7. Cross-run fingerprinting — re-run, ARIP recognises repeats"
moment "DEMO MOMENT — same root-cause shape, seen N time(s)"

( cd "$PLAYWRIGHT_DIR" && rm -f playwright-report.json && npx playwright test 2>&1 | tail -3 || true )
sleep 8
uv_quiet run arip investigate \
    "$PWREPORT" \
    --out "$REPORT_DIR" \
    --memory "$MEMORY_DB" \
    --environment "demo"

echo
note "Memory store: investigations grouped by deterministic fingerprint"
echo
sqlite3 -header -column "$MEMORY_DB" \
  "SELECT primary_rule_id AS rule, fingerprint, COUNT(*) AS occurrences
     FROM investigations
    WHERE fingerprint IS NOT NULL
    GROUP BY primary_rule_id, fingerprint
    ORDER BY occurrences DESC"
pause_for_viewer

# ── Beat 8: trust + portability ──────────────────────────────────────

beat "8. The trust layer in one line"
moment "DEMO MOMENT — abstention, conflicting_hypotheses, low-confidence"
note "ARIP refuses to produce a primary when signals conflict or are thin."
note "See docs/abstention-gallery.md and docs/calibration-gallery.md."
note "Portable across telemetry conventions: see arip-core/configs/."

# Show signals + quality summary from one report.
demo_report=$(ls -t "$REPORT_DIR"/*.md 2>/dev/null | head -1)
if [[ -n "$demo_report" ]]; then
  echo
  awk '/^## Environment quality/,/^## [^E]/' "$demo_report" | head -16
fi

pause_for_viewer

# ── Beat 9: outputs index ────────────────────────────────────────────

beat "9. Generated outputs"
report_count=$(ls "$REPORT_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
fp_count=$(sqlite3 "$MEMORY_DB" "SELECT COUNT(DISTINCT fingerprint) FROM investigations WHERE fingerprint IS NOT NULL")
inv_total=$(sqlite3 "$MEMORY_DB" "SELECT COUNT(*) FROM investigations")

cat <<EOF
  ${BOLD}Markdown reports${RESET}        $report_count file(s) in ${REPORT_DIR#$REPO_ROOT/}/
  ${BOLD}PR comment${RESET}              ${PR_COMMENT#$REPO_ROOT/}
  ${BOLD}Memory store (SQLite)${RESET}   ${MEMORY_DB#$REPO_ROOT/}
                          $inv_total investigations · $fp_count distinct fingerprints
  ${BOLD}Jaeger UI${RESET}               http://localhost:16686
EOF
pause_for_viewer

# ── Beat 10: closing ─────────────────────────────────────────────────

beat "10. Where to go next"
cat <<EOF
  ${DIM}Read first:${RESET}      docs/ARIP_DEMO_WALKTHROUGH.md
  ${DIM}Pilot kit:${RESET}       PILOT.md
  ${DIM}Trust contract:${RESET}  docs/CALIBRATION.md
  ${DIM}Onboarding:${RESET}      docs/ONBOARDING.md
  ${DIM}Stop stack:${RESET}      docker compose down -v
EOF
echo
ok "demo complete."
