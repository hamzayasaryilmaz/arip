#!/usr/bin/env bash
#
# observe-self-audit.sh — Pre-pilot self-audit for arip observe.
#
# Runs an observe-mode pull against a tiny budget on a throwaway store
# and prints the per-band quality counts and per-cluster outcome.
# Read-only outside the throwaway store path.
#
# Goal: a 30-second answer to "is my telemetry shape ingestible AT
# ALL?" — before committing to a full pilot window.
#
# Usage:
#   bin/observe-self-audit.sh path/to/bundles.jsonl
#   bin/observe-self-audit.sh path/to/dir
#
# This is operator tooling; it shells out to `arip observe` and does
# not add any new capability to the engine or the observation module.

set -euo pipefail

if [[ "${1:-}" == "" ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: bin/observe-self-audit.sh <jsonl-or-directory>

Runs `arip observe` with --budget 5 against a temporary store and
prints the digest. Use to verify pilot readiness before committing
to a real pilot window. See docs/OBSERVE_PILOT_KIT.md.
EOF
  exit 0
fi

SOURCE="$1"
TMPDIR_AUDIT="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_AUDIT"' EXIT

STORE="$TMPDIR_AUDIT/audit.db"
DIGEST="$TMPDIR_AUDIT/digest.md"

echo "=== arip observe self-audit ==="
echo "source: $SOURCE"
echo "throwaway store: $STORE (cleaned up on exit)"
echo

uv --project "$(dirname "$0")/../arip-core" run arip observe "$SOURCE" \
  --store "$STORE" \
  --budget 5 \
  --digest-out "$DIGEST" \
  || {
    echo
    echo "self-audit FAILED — see error above"
    echo "common causes:"
    echo "  - source path does not exist"
    echo "  - jsonl file is not valid JSON per line"
    echo "  - bundle shape missing 'trace_id' or 'spans'"
    echo "  - bin/jaeger-export-to-bundles.py was not run on a Jaeger export"
    exit 1
  }

echo
echo "=== digest (truncated to first 80 lines) ==="
head -80 "$DIGEST"
echo
echo "=== self-audit signals ==="
echo "If the digest above shows:"
echo "  - 'quality band distribution: high=...' with high > 0  → ingestion is healthy"
echo "  - only 'medium=...' or 'low=...'                        → fix telemetry hygiene first"
echo "  - 'No rule-grounded recurring patterns'                 → either healthy traffic OR signals missing; see docs/OBSERVE_PILOT_KIT.md"
echo "  - 100% 'no_rule_matched' clusters                       → your telemetry shape may not match any of the 5 rules' contracts (e.g. handler-pattern, retry attrs); this is honest abstention, often pointing at a NormalizationConfig override worth making — see docs/ONBOARDING.md"
echo "  - many singleton clusters with order-IDs in operations  → P0 — file an issue, do NOT pilot"
echo
echo "Ready to run a real pilot? See docs/OBSERVE_PILOT_KIT.md."
