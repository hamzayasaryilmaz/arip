# ARIP — Operator manual

A practical handbook for someone using ARIP for the first time.
Copy-paste the commands. Each step says what you should see. No
theory, no marketing. If a section feels academic, it's a bug — open
an issue.

Target: **30 minutes from this page to your first real investigation.**

---

## 1. What ARIP actually does

A Playwright test in your CI fails. Instead of you opening the CI log,
hunting for a trace ID, switching to Jaeger, opening each span, then
checking the logs of two different services — **ARIP does all that
correlation for you and writes a markdown post-mortem with the cited
evidence.**

That report appears as a sticky comment on the PR that triggered the
failing test.

ARIP is useful when:
- You have OpenTelemetry traces of the failing request
- Your test runs in CI (GitHub Actions today; GitLab CI portable)
- Your failure is a known shape (concurrent modification, retry storm,
  downstream error, DB pool exhaustion, application-layer latency)

ARIP is **not** useful and will say so when:
- The failing trace never reached your telemetry backend
- Your telemetry is missing the signals a rule needs (e.g. no
  `retry.attempt` attribute on retry spans)
- Multiple rules fire with conflicting framings — ARIP abstains rather
  than guessing
- The failure is a pattern ARIP has no rule for yet — abstains with
  `no_rule_matched`

It does NOT replace your judgement. It removes correlation grunt work.
You still decide whether the hypothesis it offers is right.

---

## 2. Before you start

| Tool             | Minimum            | How to verify                                                |
|------------------|--------------------|--------------------------------------------------------------|
| Docker + Compose | recent (2024+)     | `docker --version && docker compose version`                  |
| Node             | 20.x               | `node --version`                                              |
| `uv`             | 0.5+               | `uv --version`                                                |
| `curl`           | any                | `curl --version`                                              |
| `python3`        | 3.10+              | `python3 --version`                                           |
| `git`            | any recent         | `git --version`                                               |

Install `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Machine:** 4 GB free RAM, 5 GB disk (Docker images + reports). The
demo stack runs locally — no cloud account, no GitHub token, no API
key needed.

You'll only need a GitHub token / SSO when running the workflow on a
real PR. That comes later.

---

## 3. First-time setup

Clone, install, bring up the local demo stack:

```bash
# 1. clone
git clone <repo-url> arip
cd arip

# 2. bring up local telemetry + demo services
docker compose up -d --wait

# 3. install Playwright (one-time, ~15 s)
( cd tests/playwright && npm install )

# 4. install ARIP core (one-time, ~20 s)
( cd arip-core && uv sync --extra dev )
```

Verify everything is up:

```bash
docker compose ps
curl -sf http://localhost:8080/healthz && echo " · payment OK"
curl -sf http://localhost:8081/healthz && echo " · inventory OK"
```

You should see 6 containers running:
`arip-jaeger`, `arip-otel-collector`, `arip-postgres`, `arip-redis`,
`arip-payment`, `arip-inventory`.

If any is missing or unhealthy, jump to [§9 Troubleshooting](#9-common-troubleshooting).

---

## 4. Run your first demo

One command runs the whole pipeline against the local demo stack:

```bash
bin/arip-demo.sh
```

What happens, in order:

1. **Preflight + bootstrap** — verifies you have everything in §2.
2. **Stack health check** — confirms the 6 services are up.
3. **Inventory reset** — so the run is reproducible.
4. **Playwright suite** — 5 tests run, 4 are designed to fail.
   You'll see 4 failures in the terminal output.
5. **Trace flush wait** — ~8 s for the OTel Collector to ship traces.
6. **ARIP investigation** — produces 4 markdown reports in `reports/`.
7. **PR-comment render** — `arip-pr-comment.md` at repo root.
8. **Second run** — to demonstrate cross-run fingerprinting.

End-to-end takes about **30 seconds** on a recent laptop.

What to look at afterwards:

```bash
# the rendered PR comment (the thing your CI would post)
cat arip-pr-comment.md

# per-failure markdown reports
ls reports/
cat reports/checkout-succeeds-without-exhausting-retries-*.md

# the in-process Jaeger UI for the full traces
open http://localhost:16686
```

Each report's "Trace:" line gives you the Jaeger URL for that trace:
`http://localhost:16686/trace/<trace_id>`.

---

## 5. Understanding the output

This is the part of the manual to read slowly. Every section in a
report has a specific role.

### TL;DR

A 2–4 sentence paraphrase of the primary hypothesis. Either:
- Deterministic prose (the rule's own description), or
- A hedged paraphrase from Claude (if `ANTHROPIC_API_KEY` is set)

The LLM **never sees raw telemetry**. It only paraphrases the
deterministic finding. There is no AI in the analysis path.

### Environment quality

A health score for the input telemetry — `high` 🟢 (≥ 0.80),
`medium` 🟡 (0.50–0.79), or `low` 🔴 (< 0.50). Includes:

- **Coverages** — per-signal: did the trace have the data each rule
  expects? E.g. `business_key_on_entry: 14/14 (100%)`.
- **Findings** — specific gaps, with severity (`critical` / `warn` /
  `info`).
- **Rules likely to fire** vs **rules that will not fire** — for this
  specific trace.

If you see `low-confidence environment`, treat the primary hypothesis
as a hint, not a conclusion. The diagnostics table tells you exactly
what's missing.

### Primary hypothesis

The engine's strongest finding. Has:

- **Title** — what the engine thinks is going on
- **Severity** (`high` / `medium`)
- **Confidence** (numeric, 0.0–1.0) — function of how many corroborating
  signals the rule found
- **Rule** — which of the five rules produced this finding
- **Suggested next step** — concrete, not generic
- **Evidence** — every span_id / log line cited here exists in the
  live telemetry (audited)

Confidence bands the engine cares about:
- **≥ 0.85** — trust ceiling; engine commits
- **0.70–0.84** — primary, but read alternatives too
- **< 0.70** — engine usually abstains rather than promote this

### Alternative hypotheses

Other rules that also fired, ranked. Read them. In some failures
the primary is right and alternatives are noise; in others the
alternatives are the actual signal. The cheat code: **the rule
whose suggested next step you'd actually take is the one to trust**.

### Cross-run context

If this same root-cause shape has been seen in a previous ARIP
investigation, this section says so:

> *This same root-cause shape has been seen 7 time(s) by ARIP
> (3 of them in the last 14 days). Fingerprint: `abc123…`*

The fingerprint is `sha256(rule_id + service_set + evidence_kinds)`.
It does **not** include trace IDs or timestamps, so the same shape
matches across runs.

### Abstention

If you see `## ⚠️ Engine abstained` at the top, ARIP refused to nominate
a primary. Four reasons (codes):

- `no_primary_trace` — the failing trace never reached Jaeger
- `empty_telemetry` — no spans or logs for the failure window
- `no_rule_matched` — telemetry shape doesn't fit any shipped rule
- `conflicting_hypotheses` — multiple rules fired at similar
  confidence on disjoint evidence; engine declines to pick one
- `weak_evidence` — best hypothesis has too few evidence kinds

This is **a feature, not a failure mode**. See [§8 Trust model](#8-trust-model).

### Request timeline

Spans + logs + DB queries sorted by timestamp. Use this to walk through
what actually happened, in order. Particularly useful when the primary
hypothesis is right but you want to confirm "why" before acting.

### Evidence index

Jaeger URLs for every trace cited. Click through, verify the spans
look as the report describes. If the cited span doesn't exist or
doesn't match — that's an evidence-audit bug; open an issue.

For real annotated examples, see:

- [docs/examples/retry_storm-rca.md](examples/retry_storm-rca.md)
- [docs/examples/pool_exhaustion-rca.md](examples/pool_exhaustion-rca.md)
- [docs/examples/concurrent_modification-rca.md](examples/concurrent_modification-rca.md)
- [docs/examples/downstream_error-rca.md](examples/downstream_error-rca.md)
- [docs/examples/abstention.md](examples/abstention.md)

---

## 6. How to investigate a real failure

Once the demo works, here's the workflow against your own CI's failure.

### Step 1 — Capture the failure

You need one Playwright run's JSON report:

```bash
# in your project's CI workflow, after `playwright test`:
cat playwright-report.json    # this is what ARIP consumes
```

The test must annotate its `trace_id` so ARIP can correlate. See
[tests/playwright/trace-extractor.ts](../tests/playwright/trace-extractor.ts) — the
pattern is:

```typescript
testInfo.annotations.push({ type: "trace_id", description: traceId });
testInfo.annotations.push({ type: "order_id", description: businessKey });
```

If your tests don't yet do this, the easiest fix is to capture the
trace ID from the `X-Trace-Id` response header your services set,
or wrap your client to read it.

### Step 2 — Preflight against your telemetry

Before running a full investigation, check whether your telemetry
has the signals ARIP's rules expect:

```bash
cd arip-core
uv run arip preflight ../path/to/your/playwright-report.json
```

Output tells you:
- Environment quality score
- Per-signal coverage
- Which rules can fire on your trace, which can't

If quality is `low` with critical findings, fix those before
investigating. Investigation on broken telemetry is unhelpful at best
and misleading at worst.

### Step 3 — Write a config (only if defaults don't match)

ARIP defaults to standard OpenTelemetry conventions. If your
attributes have different names:

```bash
cp arip-core/configs/demo.yaml configs/<yourproject>.yaml
$EDITOR configs/<yourproject>.yaml
```

Only edit fields whose names differ in your telemetry. The full
field reference is in [docs/ONBOARDING.md](ONBOARDING.md).

### Step 4 — Run the investigation

```bash
uv run arip investigate ../path/to/your/playwright-report.json \
  --config ../configs/<yourproject>.yaml \
  --out ../reports/
```

Reports land in `reports/<test-slug>-<hash>.md`. Plus JSON twins.

### Step 5 — Render a PR comment

```bash
uv run arip pr-comment ../reports/ --out ../arip-pr-comment.md
```

That file is what your CI workflow would post on a PR. Open it,
read it.

### Step 6 — Wire up the workflow

When the local round-trip is working, set up the GitHub Actions
workflow. The reference is at [.github/workflows/arip-investigate.yml](../.github/workflows/arip-investigate.yml).
The key part is the sticky-comment action:

```yaml
- uses: marocchino/sticky-pull-request-comment@v2
  with:
    path: arip-pr-comment.md
    header: arip-investigation
```

That `header` makes re-runs update the same comment instead of
posting a new one each time.

---

## 7. How to onboard a new repo

The portability claim is: **a different repo with different
telemetry conventions adopts ARIP by writing one config file, not
new code.**

### Minimum viable telemetry

Without these, ARIP cannot work at all:

1. **OpenTelemetry traces** for your services
2. **Per-failure `trace_id`** that the failing Playwright test
   annotates
3. **Span `status` ERROR** for HTTP 5xx (otelhttp / equivalent
   middleware does this)
4. **Structured (JSON) logs** that include `trace_id` (so ARIP can
   correlate logs to the failing trace)

Anything beyond this is optional and just unlocks specific rules.

### The config file

Open `arip-core/configs/demo.yaml`. Every field is documented inline.
Most environments only need to override 1–3 fields:

```yaml
name: my-project

# If your business key is named differently:
business_keys:
  - account.id     # was order.id

# If your retry policy emits different attribute names:
retry:
  attempt_attr:  http.retry.attempt_number   # was retry.attempt
  reason_attr:   http.retry.cause            # was retry.reason

# If your handler operation names follow a different convention:
handler_operation_patterns:
  - "Controller#"   # Spring style
  - "Resource."     # JAX-RS style
  - handle_         # keep the default too
```

Use `arip preflight` after each edit to see which rules become ready.

### Common onboarding problems

| Symptom                                                           | Fix                                                              |
|-------------------------------------------------------------------|-------------------------------------------------------------------|
| All rules say "missing required signal"                            | Defaults don't match — copy `configs/demo.yaml` and edit         |
| `business_key_on_entry: 0/N (0%)`                                  | Add your business-key attribute name to `business_keys:` list    |
| `retry_storm` doesn't fire on traces you know retried              | Your retry instrumentation isn't tagging spans — fix at source   |
| `db_pool_exhaustion` never fires                                   | Pool stats not emitted — out of scope unless you instrument them |
| Engine always abstains with `no_primary_trace`                     | Trace flush latency — increase the sleep in `bin/arip-e2e.sh`    |

Long form: [docs/ONBOARDING.md](ONBOARDING.md).

---

## 8. Trust model

This is the operator-facing version of [docs/CALIBRATION.md](CALIBRATION.md).
Read it before deciding whether to act on a primary hypothesis.

### When the engine is reliable

- Confidence ≥ 0.85 AND no abstention banner → primary is well-grounded
- Evidence section cites multiple kinds (span, log, span_event) →
  multi-signal corroboration
- Environment quality is `high` 🟢

In this case, the primary hypothesis is usually right. Verify with
the trace link, then act.

### When the engine is hedging

- Confidence 0.70–0.84 → primary is the best the engine can say,
  but read alternatives before acting
- Environment quality is `medium` 🟡 → some signals were missing;
  the primary may be partial
- Alternative hypotheses are within 0.10 of the primary → competing
  explanations; weigh manually

### When the engine refuses

- `## ⚠️ Engine abstained` banner at the top → no primary nominated.
  Don't go hunting for one in the alternatives — abstention is a
  contract, not a bug. Read the abstention code:

  - `no_primary_trace` — telemetry problem, not a finding
  - `no_rule_matched` — novel failure shape, manual investigation needed
  - `conflicting_hypotheses` — read ALL candidates; the engine
    correctly refused to pick one for you
  - `weak_evidence` — top finding is too thin; treat the candidate
    as a hint, not a conclusion

### Low-confidence environment

If the top of the report says **low-confidence environment**:
- The telemetry is materially incomplete
- Every confidence number in the report is suspect
- Treat the report as a "where to look", not "what to fix"
- Improve the telemetry gaps the assessment listed, then re-run

### Things ARIP will never claim

- "This is the root cause." (Closest it gets: "primary hypothesis,
  confidence 0.94, evidence: X")
- "The system is fixed."
- "Trust me." (It cites evidence; you verify.)

### Things ARIP will sometimes claim that you should still verify

- Specific span_ids in evidence — click through to Jaeger and look
- Log-line citations — they exist (audited), but the *interpretation*
  is the engine's; you decide if it's right
- Cross-trace correlation via business keys — works when keys are
  consistent, falls apart on naming drift

---

## 9. Common troubleshooting

### `bin/arip-demo.sh` fatal-errors on preflight

The script says exactly which tool is missing. Install it per §2
and re-run.

### `docker compose up` hangs or some services unhealthy

```bash
# nuke everything and rebuild fresh
docker compose down -v
docker compose up -d --wait
docker compose ps
```

If Postgres won't start: `lsof -i :5432` — something else has the
port. Stop the other Postgres or change the port in `docker-compose.yml`.

### Playwright tests don't produce a report

```bash
cd tests/playwright
rm -f playwright-report.json
npx playwright test
ls -l playwright-report.json    # should exist, > 0 bytes
```

If still missing: `npm install` again (deps incomplete).

### Engine abstains with `no_primary_trace`

Trace hasn't reached Jaeger yet. The OTel Collector batches every 5 s;
ARIP's runners wait 8 s by default. Slow machine? Edit
`bin/arip-e2e.sh`:

```bash
# bump from 8 to 12 seconds
sleep 12   # was: sleep 8
```

### No reports generated in `reports/`

Check whether any Playwright tests actually failed:

```bash
cd tests/playwright
python3 -c "
import json
d = json.load(open('playwright-report.json'))
print('stats:', d.get('stats'))
"
```

`unexpected: 0` means everything passed. ARIP only investigates
failures.

### Jaeger UI shows no traces

```bash
# check the collector is forwarding to jaeger
docker logs arip-otel-collector --tail=20
docker logs arip-jaeger --tail=20

# verify the trace pipeline directly
curl -s http://localhost:16686/api/services
```

If services list is empty: nothing flushed yet. Wait 10 s and retry.
If still empty: the collector config is broken (see
`demo-env/otel-collector/config.yaml`).

### PR comment not posting on real PR

- Workflow logs in GitHub Actions
- Check the sticky-comment step's `path:` matches where ARIP wrote
  the file (`arip-pr-comment.md`, relative to repo root)
- Ensure the workflow has `permissions: pull-requests: write`

### "It says 'low-confidence environment'"

That's working as designed. See [§8 Trust model](#8-trust-model).
Read the findings, fix what they tell you to fix in your telemetry,
re-run.

### "It says 'conflicting_hypotheses'"

Also working as designed. Read ALL the candidates listed in the
"Candidate findings" section. The engine refused to pick one
*because picking one would have been wrong*. See
[docs/abstention-gallery.md](abstention-gallery.md).

---

## 10. Realistic expectations

ARIP **is**:
- A deterministic CI investigation engine
- A reader of your existing OTel telemetry
- A producer of evidence-grounded post-mortem reports
- A workflow companion that lives in PR comments

ARIP **is not**:
- A telemetry collector (use OpenTelemetry)
- A telemetry storage backend (use Jaeger / Tempo / Loki)
- An APM platform (use Datadog / Honeycomb / etc.)
- A dashboard tool (use Grafana)
- An autonomous AI agent (it doesn't act; it reports)
- An incident-response system (use PagerDuty)
- A replacement for engineer judgement (it removes correlation work,
  not decision work)
- A real-time alerting system (it runs after CI fails)
- A self-healing or auto-remediation system

If anyone tries to position ARIP as one of the "is not" items in a
PR, point them at [docs/POSITIONING.md](POSITIONING.md) and this
section. Those constraints are load-bearing — they protect the
moat.

---

## 11. Suggested first pilot

Before piloting in your real environment, think about whether it's a
good fit.

Good first pilot:
- 50–300 engineers (smaller → not enough volume; larger → procurement-bound)
- OpenTelemetry adopted across services
- Playwright (or Cypress, with a small patch) in CI
- GitHub Actions
- One engineer willing to spend ~30 minutes reading a report and
  telling you what they thought
- Test flakiness is a real pain point on the team

Bad first pilot:
- No OTel adopted (re-instrumentation cost kills the pilot)
- Pre-product startup (CI isn't mature enough to surface useful
  failures)
- Procurement-driven enterprise (the pilot will get stuck in legal
  review, not engineering)
- "Replace our APM" expectations — that's not what ARIP does

What to measure (≤ 30 minutes from clone to first PR comment):

- **Time** — from `git clone` to first sticky PR comment
- **Trust** — did the pilot engineer trust the primary hypothesis,
  partially trust it, or distrust it?
- **Misleading bits** — anything in the report that subtly steered
  them wrong, even minor
- **One concrete change** — if they could change one thing, what

What to write down in `pilot-archive/<pilot-id>/feedback.md` — the
template is in `pilot-archive/_template/feedback.md`.

The full per-session procedure is in
[docs/PILOT_RUNBOOK.md](PILOT_RUNBOOK.md).
The trust-analytics metric definitions are in
[docs/PILOT_METRICS.md](PILOT_METRICS.md).

---

## 12. Operator mindset

The single most important thing to internalise:

> **ARIP is not an "automatic root cause oracle."**
>
> **ARIP is an evidence-grounded investigation assistant.**

Specifically:

- It removes the **correlation work** of investigation (finding the
  trace ID, opening Jaeger, filtering logs by trace, identifying
  interesting spans, building a chronological timeline). It does NOT
  remove the **decision work** (is this the actual cause? what should
  we do about it?).

- It is honest about uncertainty. When you see `confidence 0.94`, the
  engine is saying "the corroborating signals are strong." It is NOT
  saying "this is right." You still verify by clicking the trace link.

- It abstains when it should. An abstention is information — it tells
  you the engine has reached the limit of its rules' coverage *for
  this telemetry shape*. Treat abstentions as a feature, not a defect.

- It will sometimes be wrong. The calibration benchmark explicitly
  enforces "no high-confidence wrong RCAs", but lower-confidence
  primaries are calibrated to be hedges. If you treat every primary
  as gospel, ARIP will eventually let you down. If you treat every
  primary as a starting point for verification, it will not.

- Engineer judgement is required. ARIP is good at reading a trace.
  You are good at knowing your system. Those skills compose; neither
  replaces the other.

If you walk away thinking ARIP "will find root causes for you", you
will be disappointed. If you walk away thinking ARIP "will compress
the 25-minute correlation slog into 90 seconds", you will be right.

---

## What success looks like

After reading this manual once and following §3 and §4, you should
be able to:

1. Bring up the demo stack on your laptop (5 min)
2. Run a full ARIP investigation against the demo (1 min)
3. Open the rendered PR comment and one full report (3 min)
4. Identify which rule fired and why (5 min)
5. Walk through the trace in Jaeger that the report cites (5 min)
6. Identify the abstention case (`flaky_dependency`) and read why the
   engine refused to nominate a primary (3 min)
7. Decide whether ARIP is worth investigating against your own
   telemetry (8 min)

Total: 30 minutes. If that bar is missed, the manual has failed and
the issue belongs in the manual — open a PR.

## Where to go next

- Run a real pilot — [PILOT.md](../PILOT.md) (why) and
  [docs/PILOT_RUNBOOK.md](PILOT_RUNBOOK.md) (how)
- Onboard a non-demo repo — [docs/ONBOARDING.md](ONBOARDING.md)
- Read the trust contract in detail — [docs/CALIBRATION.md](CALIBRATION.md)
- Understand why ARIP refuses to claim things —
  [docs/abstention-gallery.md](abstention-gallery.md)
- Read positioning before discussing scope with anyone —
  [docs/POSITIONING.md](POSITIONING.md)
- Run `arip observe` against archived telemetry to see which anomaly
  patterns recur over time — [docs/OBSERVE_MODE.md](OBSERVE_MODE.md)
  (Phase A, observation-only)
