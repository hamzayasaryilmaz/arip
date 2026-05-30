# Production deployment guide

How to deploy ARIP into a real CI/staging pipeline as a working
investigation tool. Written for the operator who's run the demo,
read OBSERVE_PILOT_KIT.md, and is now wiring ARIP into their (or
their customer's) production setup.

This guide assumes you've already:
- Run the local demo (`bin/arip-demo.sh`) end-to-end
- Read [POSITIONING.md](POSITIONING.md) so you know what ARIP is and isn't
- Have a target CI system + telemetry backend in mind

## Architecture

ARIP is intentionally simple. There's no central server, no
hosted control plane, no SaaS. The production architecture is:

```
┌──────────────────────┐    1. test fails        ┌──────────────────────┐
│  Customer's CI       │ ─────────────────────►  │  Customer's CI       │
│  (Playwright/Cypress)│   playwright-report.json│  (still running)     │
└──────────────────────┘                          └──────────┬───────────┘
                                                              │
                                          2. invoke arip      │
                                                              ▼
                                                  ┌──────────────────────┐
                                                  │  ARIP (Python)       │
                                                  │  - parse report       │
                                                  │  - query Jaeger       │
                                                  │  - apply 5 rules      │
                                                  │  - audit evidence     │
                                                  │  - render report      │
                                                  └──────────┬───────────┘
                                                              │
                                                3. read from  │
                                              ┌───────────────┴─────────┐
                                              ▼                          ▼
                                  ┌─────────────────┐         ┌─────────────────┐
                                  │  Telemetry      │         │  Logs           │
                                  │  (Jaeger/Tempo/ │         │  (Loki/ES/      │
                                  │   ES/Honeycomb) │         │   Docker)       │
                                  └─────────────────┘         └─────────────────┘
                                              │
                                4. write       │
                                              ▼
                                  ┌─────────────────────────┐
                                  │  Sticky PR comment      │
                                  │  on GitHub/GitLab        │
                                  └─────────────────────────┘
```

No deployed services, no databases (except a small SQLite for
cross-run memory), no backend processes. Each CI run invokes
ARIP fresh.

## Deployment topology options

Three real options. Pick based on customer's constraints.

### Option 1 — In-CI invocation (recommended)

ARIP runs as a step inside the same CI workflow as the tests.

```
┌────────────────────────────────────────────────────────┐
│ GitHub Actions workflow                                │
│                                                        │
│  1. docker compose up    (customer's services)         │
│  2. npx playwright test  (customer's tests)            │
│  3. uv run arip investigate playwright-report.json     │  ◄── ARIP runs here
│  4. post sticky comment  (marocchino action)           │
└────────────────────────────────────────────────────────┘
```

**Pros:**
- Simplest setup; everything in one workflow
- No external infrastructure
- ARIP has direct access to test report + Jaeger UI port
- Reproducible per-PR

**Cons:**
- CI workflow takes 20-60 sec longer
- ARIP only runs when CI runs (no scheduled observation)

**Best for:** customers with PR-triggered CI as their primary
quality gate. Default choice.

### Option 2 — Scheduled GitHub Actions (observe-mode)

ARIP runs on cron, pulling from production telemetry, posting
weekly digests.

```
┌────────────────────────────────────────────────────────┐
│ GitHub Actions workflow (cron: weekly)                 │
│                                                        │
│  1. pull telemetry from production Jaeger/Tempo        │
│  2. convert via bin/jaeger-export-to-bundles.py        │
│  3. uv run arip observe bundles.jsonl                  │
│  4. post digest to sticky issue comment                │
└────────────────────────────────────────────────────────┘
```

Template: `.github/workflows/arip-observe.yml.example`

**Pros:**
- Catches recurring patterns CI alone misses
- Reports stack up over time, recurrence becomes visible
- No customer-side infrastructure beyond GitHub Actions

**Cons:**
- Needs read access from CI runner to production telemetry
- Cron lag (weekly digest = 1-week feedback delay)

**Best for:** customers with mature observability who want
ongoing pattern detection beyond per-failure RCA.

### Option 3 — Self-hosted runner / on-prem

ARIP installed on a customer-owned machine, runs as cron or
on-demand. Useful when:
- Production telemetry is behind firewalls GitHub Actions can't reach
- Customer prefers no cloud CI involvement
- Compliance reasons

**Setup:**
- Install `uv` + Python 3.12+ on the host
- Clone the repo
- `uv sync --extra dev`
- Add cron entry OR systemd timer pointing at `bin/run-observe-pilot.sh`

**Pros:**
- Full data sovereignty
- No external dependency

**Cons:**
- Customer must maintain the host
- No automatic PR comment integration (manual)

**Best for:** regulated industries, air-gapped environments.

## Step-by-step: Option 1 production setup

This is the most common path. ~30 minutes for a typical setup.

### Step 1 — Prerequisites check

On the operator's laptop, verify customer's environment is
ARIP-ready:

```bash
# Export 1 hour of telemetry from customer's Jaeger
curl -s "$JAEGER/api/traces?service=$SERVICE&lookback=1h&limit=200" \
  > /tmp/customer-traces.json

# Convert + observe
python3 bin/jaeger-export-to-bundles.py \
  --in /tmp/customer-traces.json \
  --out /tmp/customer-bundles.jsonl

bin/observe-self-audit.sh /tmp/customer-bundles.jsonl
```

Expected outcome: digest is produced, quality band is at least
`medium`, no `prerequisite_failure`. If prerequisite fails, STOP
— address the telemetry gap before proceeding. See
[INGESTION_GUIDE.md](INGESTION_GUIDE.md) "Workflow 0".

### Step 2 — Build the NormalizationConfig

Create `configs/arip/<env>.yaml` in customer's repo:

```yaml
name: "customer-production"

# Business key — what is the entity ID flowing through your
# distributed flows? Adjust to match.
business_keys:
  - order.id              # default; replace with yours
  - account.id            # additional, if applicable

# Aliases — if the key gets renamed across services
business_key_aliases:
  order.id:
    - payment.order_ref
    - shipment.order_no

# Operator-declared coverage assertions (makes ARIP loud about gaps)
expected_services_per_trace:
  - frontend
  - cart-service
  - payment-service
  - inventory-service

expected_log_sources:
  - frontend
  - payment-service

# Retry signal names — adjust if you use a custom convention
retry:
  attempt_attr: retry.attempt          # default; matches OTel
  max_attempts_attr: retry.max_attempts
  backoff_attr: retry.backoff_ms
  reason_attr: retry.reason
  policy_attr: retry.policy

# DB
db:
  system_attr: db.system
  pool:
    acquired_attr: db.pool.acquired
    max_attr: db.pool.max
    wait_ms_attr: db.pool.wait_ms

# Handler operation patterns — what naming style does your code use?
# Examples:
#   Spring controllers:    ["Controller#"]
#   Go HTTP routers:       ["/api/", "/v1/"]
#   gRPC services:         ["Service/"]
handler_operation_patterns:
  - "Controller#"      # adjust for your code
  - "/api/"

# State transitions (only if you emit them for the
# concurrent_modification rule)
state_transitions:
  event_name: state.transition
  from_attr: state.from
  to_attr: state.to
```

Test it locally:

```bash
uv run arip investigate /tmp/sample-report.json \
  --config configs/arip/customer-production.yaml \
  --out /tmp/test-reports
```

### Step 3 — Add the CI workflow

Copy `.github/workflows/arip-investigate.yml` from the ARIP repo to
the customer's `.github/workflows/`. Adjust:

```yaml
- name: Run ARIP investigation
  working-directory: arip-core
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}  # optional
  run: |
    uv run arip investigate \
      ../tests/playwright/playwright-report.json \
      --out ../reports \
      --memory ../.arip/memory.db \
      --config ../configs/arip/customer-production.yaml \
      --environment "ci"
```

For Cypress instead of Playwright, change the report path; ARIP
auto-detects.

### Step 4 — Configure the sticky PR comment

Use the `marocchino/sticky-pull-request-comment@v2` action:

```yaml
- name: Post PR comment
  if: github.event_name == 'pull_request'
  uses: marocchino/sticky-pull-request-comment@v2
  with:
    path: arip-pr-comment.md
    header: arip-investigation
```

The `header: arip-investigation` ensures the same comment is
updated (not duplicated) across multiple workflow runs.

### Step 5 — Enable cross-run memory caching

```yaml
- name: Cache ARIP memory across runs
  uses: actions/cache@v4
  with:
    path: .arip
    key: arip-memory-${{ github.repository }}
    restore-keys: |
      arip-memory-
```

This persists the SQLite memory store across CI runs, enabling
"seen 7 times in the last 14 days"-style cross-run intelligence.

### Step 6 — First run + verification

Create a test PR with a deliberately-failing test. Verify:

1. ARIP step runs to completion (check workflow logs)
2. Sticky comment appears on the PR
3. Cited spans/logs in the report actually exist (click into
   Jaeger to verify)
4. If ARIP abstained, the `next_step` hint is actionable

### Step 7 — Handover

Provide the customer engineering owner:

1. URL of the customer's ARIP workflow
2. Path to the `NormalizationConfig` (so they can adjust)
3. Brief: "When ARIP abstains, read the next_step. When it
   produces a primary, verify the cited evidence before acting."
4. Where to file bugs (your email + GitHub issues on the ARIP
   repo)

## Operations after deployment

### When things go right

- ARIP report appears on failing PRs
- Cited evidence checks out in Jaeger
- Cross-run memory accumulates fingerprints
- Customer engineers learn the abstention vocabulary

### Common operational issues

#### "ARIP abstains on most failures"

Likely cause: telemetry hygiene gap. Run the audit again, identify
what's missing, fix at the source. Common culprits:
- Logs without `trace_id` MDC
- Service not emitting OTel
- Custom HTTP middleware that strips traceparent header

#### "ARIP reports are slow (> 60s)"

Likely cause: telemetry backend latency or large trace count.
Check:
- Jaeger query response time directly via curl
- ARIP's own runtime: `time uv run arip investigate ...`
- Reduce `--budget` for observe-mode if applicable

#### "Memory.db grows large"

Expected. After 6 months of CI activity, expect ~50-100 MB.
Acceptable. If you must, prune via:

```python
# Run in arip-core/.venv
from arip_core.memory.store import MemoryStore
m = MemoryStore(".arip/memory.db")
m.prune_investigations_older_than(180)  # if such a method exists
```

(As of v0.1.0, memory pruning is manual / not built-in. Doc gap;
add to backlog.)

#### "Customer wants to change a rule's behavior"

Don't modify the shipped rules. Options:
1. Adjust `NormalizationConfig` if the issue is signal mapping
2. Write a custom rule (separate engagement)
3. Document the desired behavior as a calibration scenario and
   propose upstream contribution

## Monitoring ARIP itself

ARIP doesn't have built-in metrics emission (anti-goal: observability
platform). What you CAN monitor:

| Signal | How |
|---|---|
| Workflow success rate | GitHub Actions API |
| ARIP investigation duration | Parse workflow run logs |
| Report content (cluster types, abstentions) | Parse generated markdown files |
| Memory store size | `ls -la .arip/memory.db` |
| False-confidence rate | Quarterly manual review of N reports |

The "false-confidence rate" check is the most important. Once a
quarter:

1. Sample 20 random reports from the last 90 days
2. For each: check if the cited evidence ACTUALLY supports the
   primary hypothesis
3. Count: how many are confidently wrong?
4. Target: < 5%
5. If higher: stop using ARIP for that telemetry source until
   the cause is identified

This is the calibration discipline. Skip it, lose trust.

## Updating ARIP

ARIP is a `git pull` away from latest.

```bash
cd arip
git pull origin main
cd arip-core
uv sync --extra dev
uv run pytest -q  # ensure 223/223 still green
```

Production updates:
1. Test on a branch first
2. Check the calibration benchmark still passes
3. Roll forward in CI workflow
4. Watch the next 5 runs for unexpected behavior changes

ARIP has no versioned API; the only stable surface is the
`NormalizationConfig` schema. Upstream may add fields; missing
fields fall back to defaults.

## Disaster recovery

There's not much to recover. ARIP has:
- No persistent server
- No external database
- No queue
- One SQLite file (`.arip/memory.db`) — gitignored, cached by CI

If the memory.db is lost:
- Next CI run rebuilds it
- Cross-run intelligence resets (loses the "seen N times" context)
- No correctness impact on individual reports

If the ARIP repo / fork is lost:
- It's Apache-2.0 on GitHub at https://github.com/hamzayasaryilmaz/arip
- Re-clone, re-sync, re-run

The "no infrastructure" architecture means disaster recovery is
trivial. This is by design.

## When NOT to deploy ARIP

If any of these are true, deploying ARIP wastes everyone's time:

- Customer doesn't have distributed tracing
- Customer's failures don't fit any of the 5 rules
- Customer expects ARIP to take action (open PRs, send alerts)
- Customer wants a dashboard
- Customer's CI doesn't produce a structured failure report
  (raw stderr output won't work)

In any of these cases, refer back to the audit findings or
revisit the fit conversation.

## Cross-references

- [OBSERVE_PILOT_KIT.md](OBSERVE_PILOT_KIT.md) — pilot kit
- [INGESTION_GUIDE.md](INGESTION_GUIDE.md) — adapter recipes
- [ONBOARDING.md](ONBOARDING.md) — telemetry prerequisites
- [POSITIONING.md](POSITIONING.md) — anti-goals
- [COMMERCIAL_OFFERINGS.md](COMMERCIAL_OFFERINGS.md) — engagement structure
- `.github/workflows/arip-investigate.yml` — CI workflow template
- `.github/workflows/arip-observe.yml.example` — observe-mode workflow template
