# Calibration & Trust Benchmark

What this document is: the **gate** between ARIP's deterministic
investigation MVP and any "general-purpose" production deployment.

ARIP is allowed to be wrong (no production system is omniscient).
What ARIP is **not** allowed to be is **confidently wrong**. The trust
benchmark below is the standing test of that property.

## The trust metric

> **Would this RCA send an engineer in the wrong direction?**

For every investigation ARIP produces, we ask one binary question:

- ✅ The engineer reads the primary hypothesis (or the abstention)
  and goes to investigate the right component.
- ❌ The engineer reads the primary hypothesis and goes to investigate
  the wrong component, *while* a more accurate alternative was visible
  in the same report.

Honest abstention always counts as ✅. A high-confidence wrong primary
always counts as ❌. The number of ❌ across the benchmark scenarios
is the only number that matters for production readiness.

## Reasoning-quality layer

The engine has four explicit guards against confidently-wrong RCAs.
Adding new rules without preserving these guards is a regression and
should be caught in code review.

### 1. Evidence audit
`arip_core/engine/evidence_audit.py` — every cited reference
(`span_id`, `trace_id`, log description) must exist in the live
telemetry. Ungrounded evidence is dropped; confidence decays
proportionally; hypotheses left with zero evidence are silently
removed.

### 2. Rule template hardening
Rules must validate absolute claims against the actual telemetry
before emitting them.

- `downstream_error` only writes *"every span above is ERROR-tagged"*
  after walking the full ancestor chain and confirming it. When the
  chain is partial (e.g. retry recovered), the rule explicitly says
  *"the upstream eventually recovered (e.g. via retry) or the error
  was localised"*, drops confidence to 0.75, and renames the title to
  *"failure observed (recovered upstream)"*.
- `retry_storm` only writes *"every attempt failed with the same
  reason"* and *"persistent downstream condition"* when **all** the
  attempt spans are ERROR-tagged. In partial-failure cases it says
  *"only N of M attempts errored — the retry policy recovered"*, and
  declines to apply the consistent-reason confidence bonus.
- *Per-attempt downstream evidence* uses *"each of the N attempts hit
  ERROR"* only when every attempt did; otherwise *"K of N attempts hit
  ERROR — transient blip, not persistent failure"*.

### 3. Assertion-aware adjustment
`arip_core/engine/assertion.py` — the test's assertion (e.g.
"checkout returns 200", "checkout completes within 150ms",
"order history has no interleaved trace_ids") is classified into
**latency / status / correctness / retry** tags. Rules whose root-cause
category aligns with the assertion get a small confidence boost
(+0.03); misaligned rules get a small decay (−0.03). Soft re-ranking,
not a rewrite — the rule's own confidence formula stays primary.

### 4. Conflicting-hypotheses abstention
`arip_core/engine/abstention.py` — a new abstention code
`conflicting_hypotheses` fires when:

- the top hypothesis is **below** the ceiling (0.85) — if it were
  higher, the engine's own ranking is strong enough to trust;
- both the top and a competitor have confidence ≥ 0.7;
- both have at least 2 evidence kinds;
- their confidence delta is < 0.10 (neither has cleanly won);
- their cited evidence overlaps less than 30% (they point at
  different parts of the trace).

In that case ARIP refuses to nominate a primary and surfaces all
candidates so a human can weigh them.

## Canonical benchmark scenarios

These are the scenarios the trust benchmark validates against. Adding
a new failure pattern means adding a row here.

| # | Scenario              | Expected primary           | Expected confidence | Engine behaves as expected? |
|---|-----------------------|----------------------------|---------------------|------------------------------|
| 1 | `slow_query`          | `latency_vs_db`            | ≥ 0.80              | ✓ (manual; not in suite)     |
| 2 | `inventory_error`     | `downstream_error`         | ≥ 0.85              | ✓                            |
| 3 | `webhook_race`        | `concurrent_modification`  | ≥ 0.85              | ✓                            |
| 4 | `pool_exhaustion`     | `db_pool_exhaustion`       | ≥ 0.85              | ✓                            |
| 5 | `retry_storm`         | `retry_storm`              | ≥ 0.85              | ✓                            |
| 6 | `flaky_dependency`    | **abstention** (`conflicting_hypotheses`) | —      | ✓                            |

The last row is the **stress benchmark**. It is deliberately kept in
the codebase as a mixed-signal trace ARIP must keep declining to
auto-resolve.

## flaky_dependency — the canonical mixed-signal benchmark

`flaky_dependency` is the gate test for trustworthiness. It is the
shape of failure that:

- looks like a partial `retry_storm` (the retry policy fires),
- looks like a partial `downstream_error` (one downstream call ERROR'd),
- looks like a partial `latency_vs_db` (handler is slow vs DB),

but **none of those rules is individually the right RCA** — the test
fails for a fourth reason: cumulative latency exceeded the asserted
SLA, *because* the retry policy + the slow recovered path added up.

### Reproduce

```bash
# Bring up stack (skip if already up)
docker compose up -d --wait

# Reset inventory so the per-order counter starts fresh
docker compose exec -T postgres psql -U arip -d arip -q -c \
  "INSERT INTO inventory (sku, stock) VALUES ('SKU-001', 100) \
   ON CONFLICT (sku) DO UPDATE SET stock = 100;"

# Fire one request — expect HTTP 200 but elapsed ~340ms
ORDER_ID="ORD-FLAKY-$(date +%s)"
curl -si -X POST http://localhost:8080/checkout \
  -H 'content-type: application/json' \
  -H 'X-Failure-Mode: flaky_dependency' \
  -H 'X-Arip-Capture: true' \
  -d "{\"order_id\":\"$ORDER_ID\",\"sku\":\"SKU-001\",\"quantity\":1}"
```

Then synthesize a `FailureEvent` with the SLA-violation assertion and
run the engine — see the harness used in
[ARIP_CLAUDE_CODE_MASTER_PROMPT.md](../ARIP_CLAUDE_CODE_MASTER_PROMPT.md)
context for an inline Python invocation pattern.

### Expected output shape

```
ABSTAIN: conflicting_hypotheses
  headline: Multiple plausible but conflicting explanations.

  retry_storm        conf=0.79   (transient, recovered — softened title)
  downstream_error   conf=0.72   (recovered upstream — softened title)
  latency_vs_db      conf=0.88   (correctly identifies the handler-side latency)
```

Key properties to verify on every release:

1. **No primary nominated.** `result.primary is None`.
2. **Abstention code = `conflicting_hypotheses`.** Not `weak_evidence`
   or `no_rule_matched`; those would indicate a regression in conflict
   detection.
3. **Softened templates.** Both `retry_storm` and `downstream_error`
   say "recovered" / "transient" rather than "every attempt failed" /
   "every span above is ERROR-tagged".
4. **All three candidates visible in the report.** The engineer can
   read each and decide.
5. **`latency_vs_db` has the highest post-adjustment confidence (0.88).**
   Even though it's ranked third by severity, its confidence reflects
   that it aligns best with the failed SLA assertion.

If any of these regress, the trustworthiness layer has cracked.

## What changed in the engine to get here

Diffs of the trustworthiness pass (search-friendly):

- `engine/rules/downstream_error.py` — added `_full_ancestor_chain_is_error`
  validator and a partial-failure description branch with lower
  confidence.
- `engine/rules/retry_storm.py` — introduced `truly_persistent` and
  used it to gate the "every attempt failed" / "persistent downstream"
  claims and the consistent-reason confidence bonus.
- `engine/assertion.py` (new) — `classify_assertion` + `adjust_for_assertion`.
- `engine/abstention.py` — new `conflicting_hypotheses` code and
  `_detect_conflict` + `_evidence_overlap` helpers.
- `engine/hypothesis.py` — wired `adjust_for_assertion` into the
  pipeline.
- `demo-env/payment-service/handlers/checkout.go` — instrumentation
  fix: explicit `SetStatus(codes.Error, ...)` on the non-retriable
  early-exit path of `reserveInventory`, so the ancestor chain is
  honestly ERROR-tagged for the engine to read.

## What is deliberately not in this layer

Calibration / trust is a one-direction lever. Adding more **rules**
without strengthening these guards weakens the system, not
strengthens it. Items explicitly **not** included:

- Confidence calibration loop against ground-truth labels — needs
  feedback signal we have not yet built. See
  [FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md) Section 10.
- Multi-rule "soft voting" — would change the engine's identity from
  deterministic-rules to weighted-ensemble. Out of scope.
- LLM-based hypothesis ranking — same.
- A "fix-it-yourself" remediation layer. Same.

If a future rule cannot meet the hardening contract (validates its
claims, declares which assertion categories it aligns with, plays
nicely with conflict detection), it should not be merged.
