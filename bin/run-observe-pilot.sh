#!/usr/bin/env bash
#
# run-observe-pilot.sh — Single-command observe-mode pilot runner.
#
# Operational glue only. Wraps existing commands; adds no engine
# capability. Side effects are confined to:
#   - docs/observe-pilot-archive/<pilot-id>/   (template + outputs)
#   - .arip/observation-<pilot-id>.db          (per-pilot store)
#
# Does NOT mutate the input source. Does NOT modify the engine.
# Does NOT open PRs, send notifications, or call external services.
#
# Usage:
#   bin/run-observe-pilot.sh <source> <pilot-id>
#
# Example:
#   bin/run-observe-pilot.sh ./traces.jsonl op001
#
# After this script runs, the pilot runner sits with the operator
# while they read docs/observe-pilot-archive/<pilot-id>/digest.md,
# then fills in the three feedback templates from the verbatim
# conversation.

set -euo pipefail

# ---- arg validation ----------------------------------------------

if [[ "${1:-}" == "" ]] || [[ "${2:-}" == "" ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: bin/run-observe-pilot.sh <source> <pilot-id>

Arguments:
  <source>     Path to JSONL trace bundles, .jsonl.gz, or directory.
               See docs/INGESTION_GUIDE.md for adapter recipes if
               your source is Jaeger/Loki/GHA-artifact-shaped.
  <pilot-id>   Pilot identifier, format opNNN (e.g. op001, op002).

Reads the source read-only. Creates a per-pilot store and archive
directory. Pre-existing feedback templates in the archive are NOT
overwritten — only the auto-generated artefacts (digest, telemetry
summary preamble) are.

See docs/OBSERVE_PILOT_KIT.md for the full operator workflow.
EOF
  exit 0
fi

SOURCE="$1"
PILOT_ID="$2"

if [[ ! "$PILOT_ID" =~ ^op[0-9]{3}[a-z]?$ ]]; then
  echo "error: pilot-id must match opNNN or opNNNx (e.g. op001, op002b), got: $PILOT_ID" >&2
  echo "       (single lowercase letter suffix is allowed for follow-up pilots" >&2
  echo "        on the same system — e.g. op002 = baseline, op002b = with fault" >&2
  echo "        injection enabled)" >&2
  exit 2
fi

if [[ ! -e "$SOURCE" ]]; then
  echo "error: source does not exist: $SOURCE" >&2
  exit 2
fi

# ---- paths --------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_DIR="$REPO_ROOT/docs/observe-pilot-archive/_template"
ARCHIVE_DIR="$REPO_ROOT/docs/observe-pilot-archive/$PILOT_ID"
STORE="$REPO_ROOT/.arip/observation-$PILOT_ID.db"
DIGEST_PATH="$ARCHIVE_DIR/digest.md"
RAW_DIGEST_PATH="$ARCHIVE_DIR/.digest.raw.md"

if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "error: template directory missing: $TEMPLATE_DIR" >&2
  echo "(expected docs/observe-pilot-archive/_template/ — check repo state)" >&2
  exit 2
fi

# ---- archive scaffold --------------------------------------------

mkdir -p "$ARCHIVE_DIR"
mkdir -p "$(dirname "$STORE")"

# Copy templates only if they don't already exist — don't clobber
# feedback the operator has already filled in.
for tpl in operator-notes.md usability-findings.md feedback.md telemetry-summary.md; do
  if [[ ! -f "$ARCHIVE_DIR/$tpl" ]]; then
    cp "$TEMPLATE_DIR/$tpl" "$ARCHIVE_DIR/$tpl"
    # Replace placeholder pilot-id markers in fresh copies.
    sed -i.bak "s/op<id>/$PILOT_ID/g" "$ARCHIVE_DIR/$tpl"
    rm -f "$ARCHIVE_DIR/$tpl.bak"
    echo "  scaffolded $tpl"
  else
    echo "  preserved existing $tpl (not overwriting filled-in feedback)"
  fi
done

# ---- step 1: self-audit ------------------------------------------

echo
echo "=== step 1/3 — self-audit (throwaway store, --budget 5) ==="
echo
if ! "$REPO_ROOT/bin/observe-self-audit.sh" "$SOURCE" > "$ARCHIVE_DIR/self-audit.log" 2>&1; then
  echo "self-audit FAILED — see $ARCHIVE_DIR/self-audit.log"
  echo
  echo "Common causes (from observe-self-audit.sh output):"
  tail -20 "$ARCHIVE_DIR/self-audit.log"
  exit 1
fi
echo "  ✓ self-audit passed (log: $ARCHIVE_DIR/self-audit.log)"

# ---- step 2: full observe run ------------------------------------

echo
echo "=== step 2/3 — full observe run ==="
echo "  source:   $SOURCE"
echo "  store:    $STORE"
echo "  digest:   $DIGEST_PATH"
echo

uv --project "$REPO_ROOT/arip-core" run arip observe "$SOURCE" \
  --store "$STORE" \
  --budget 5000 \
  --digest-out "$DIGEST_PATH" \
  > "$RAW_DIGEST_PATH.log" 2>&1 || {
    echo "observe run FAILED — see $RAW_DIGEST_PATH.log"
    tail -20 "$RAW_DIGEST_PATH.log"
    exit 1
  }
echo "  ✓ observe run complete"

# ---- step 3: terminal summary + telemetry-summary preamble -------

echo
echo "=== step 3/3 — telemetry summary preamble ==="
echo

# Extract the structured lines from the digest's Run summary section
# so the operator doesn't have to recompute counts by hand.
RUN_SUMMARY_BLOCK="$(awk '/^## Run summary/{p=1; next} /^## /{p=0} p' "$DIGEST_PATH" || true)"

# Cluster counts: count table rows under each heading.
RULE_TABLE_ROWS="$(awk '/^## Recurring patterns/{p=1; next} /^## /{p=0} p' "$DIGEST_PATH" | grep -c '^|' || true)"
ABST_TABLE_ROWS="$(awk '/^## Recurring abstentions/{p=1; next} /^## /{p=0} p' "$DIGEST_PATH" | grep -c '^|' || true)"

# Subtract header + separator rows from table counts (if any data).
RULE_CLUSTERS=$(( RULE_TABLE_ROWS > 1 ? RULE_TABLE_ROWS - 2 : 0 ))
ABST_CLUSTERS=$(( ABST_TABLE_ROWS > 1 ? ABST_TABLE_ROWS - 2 : 0 ))

cat <<EOF

Paste this into $ARCHIVE_DIR/telemetry-summary.md's
"Ingestion outcome" and "Cluster counts in digest" sections:

------------------------------------------------------------------
$RUN_SUMMARY_BLOCK

Cluster counts in digest
- Rule-grounded clusters:       $RULE_CLUSTERS
- Abstention-grounded clusters: $ABST_CLUSTERS
- Total clusters:               $(( RULE_CLUSTERS + ABST_CLUSTERS ))
------------------------------------------------------------------
EOF

# ---- final operator handoff --------------------------------------

cat <<EOF

================================================================
=== PILOT $PILOT_ID — READY FOR OPERATOR ===
================================================================

  Now: open the digest in front of the operator.

      open  $DIGEST_PATH
      # or: cat $DIGEST_PATH | less

  Watch what they do. Do NOT narrate. After they finish reading,
  fill the three feedback templates VERBATIM from their words:

      \$EDITOR $ARCHIVE_DIR/feedback.md           # their quotes
      \$EDITOR $ARCHIVE_DIR/operator-notes.md     # your observations
      \$EDITOR $ARCHIVE_DIR/usability-findings.md # surface fixes only
      \$EDITOR $ARCHIVE_DIR/telemetry-summary.md  # paste preamble above

  Stop conditions (review BEFORE the session if you haven't):
    docs/OBSERVE_PILOT_KIT.md  →  "What 'failure' looks like"

  Commit the archive only after the operator has reviewed it for
  PII and approved attribution. See
  docs/observe-pilot-archive/README.md.

================================================================
EOF
