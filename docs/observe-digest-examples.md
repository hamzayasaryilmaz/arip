# Observe-mode digest examples (annotated)

Four worked examples a pilot runner can show to an operator before
the first session, so the operator has a sense of what the digest
looks like in different telemetry regimes. All four are real
captures from validation runs against synthetic real-world-shape
fixtures (see [PHASE_A_VALIDATION.md](PHASE_A_VALIDATION.md)) —
not from real pilots, which is why this file lives alongside the
pilot kit rather than in the archive.

The intent: calibrate the operator's expectations honestly. The
shape of a useful digest is recognisable when you have seen it
before. The shape of an unactionable one is also recognisable —
and tells you to fix telemetry first, not to push harder on the
engine.

---

## Example A — Healthy pilot digest (3 clusters)

What this looks like: a clean export of ~3 traces with one real
anomaly (retry_storm), one shape the engine couldn't ground
(weak_evidence), and one out-of-scope shape (no_rule_matched).

```markdown
# ARIP observation digest

## Run summary

- source: jsonl:///private/tmp/bundles-joined.jsonl
- traces observed: 3
- new events: 3
- idempotent skips: 0
- quality band distribution: high=1, medium=2
- rule matches: retry_storm=1
- abstentions: no_rule_matched=1, weak_evidence=1

## Recurring patterns (rule-grounded)

| rule         | recurrence | quality | services            | operations                 |
|--------------|-----------:|---------|---------------------|----------------------------|
| retry_storm  |          1 | medium  | inventory-service   | inventory.reserve_attempt  |

## Recurring abstentions

| abstention      | recurrence | services                            | operations                                  |
|-----------------|-----------:|-------------------------------------|---------------------------------------------|
| weak_evidence   |          1 | inventory-service, payment-service  | POST /checkout/order-12345, inventory.reserve |
| no_rule_matched |          1 | inventory-service                   | inventory.reserve                           |
```

**How to read this with the operator:**

- 3 traces, 3 clusters. Each trace was uniquely shaped — recurrence
  is `1` everywhere. This is what a small, mixed sample looks like.
- The single rule cluster (`retry_storm`) corroborated with both
  spans and logs — engine promoted it past `MIN_EVIDENCE_KINDS=2`.
- `weak_evidence` for a downstream-error-shaped trace that had spans
  but no log corroboration. The engine declined; that's the trust
  contract working, not a failure.
- The path-parameter operation name (`POST /checkout/order-12345`)
  appears in the abstention sample — it does NOT split the cluster
  because the abstention fingerprint is `(code, service_set)`.

**Operator-honest framing:** *"Here is one rule-grounded pattern and
two telemetry shapes the engine declined to label. Useful as a
'where to look' map; not useful as a verdict."*

---

## Example B — Noisy pilot digest (cluster explosion)

What this looks like *under the fingerprint bug fixed in
[PHASE_A_VALIDATION.md Appendix B](PHASE_A_VALIDATION.md)*. Kept
here as a reminder of what NOT to ship.

```markdown
# ARIP observation digest

## Recurring abstentions

| abstention    | recurrence | operations                          |
|---------------|-----------:|-------------------------------------|
| weak_evidence |          1 | POST /checkout/order-99000          |
| weak_evidence |          1 | POST /checkout/order-99001          |
| weak_evidence |          1 | POST /checkout/order-99002          |
| weak_evidence |          1 | POST /checkout/order-99003          |
| weak_evidence |          1 | POST /checkout/order-99004          |
| weak_evidence |          1 | POST /checkout/order-99005          |
| weak_evidence |          1 | POST /checkout/order-99006          |
| weak_evidence |          1 | POST /checkout/order-99007          |
| weak_evidence |          1 | POST /checkout/order-99008          |
| weak_evidence |          1 | POST /checkout/order-99009          |
```

**Why this is broken:** each unique path parameter became its own
fingerprint. 10 traces of the same shape → 10 singleton clusters.
Unreadable. Not actionable.

**Why we show it here:** this is the failure mode pilots will *not*
see, because the validation pass caught it. If an operator ever
sees a digest that looks like this in the wild, treat it as a P0
trust-regression and stop the pilot — something either reintroduced
the multiplicity bug or there's a new high-cardinality field
sneaking into a fingerprint.

---

## Example C — Empty pilot digest (no recurrence)

What this looks like: 200 healthy traces, no anomaly shapes.

```markdown
# ARIP observation digest

## Run summary

- source: jsonl:///private/tmp/healthy.jsonl
- traces observed: 200
- new events: 200
- quality band distribution: high=140, medium=60
- rule matches: <none>
- abstentions: no_rule_matched=200

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

| abstention      | recurrence | services            | operations          |
|-----------------|-----------:|---------------------|---------------------|
| no_rule_matched |        200 | payment-service     | POST /checkout      |

## What this digest is NOT

- Not a list of confirmed root causes — every cluster is an
  evidence-aligned observation, not a verdict.
- ...
```

**How to read this with the operator:**

- 200 traces collapsed into a single `no_rule_matched` cluster on
  `payment-service`. That's the trust contract: the engine is
  honest about not having a rule that fires on this shape.
- This is the **correct** output for healthy telemetry. Operators
  sometimes interpret an empty digest as "ARIP isn't working" — the
  honest framing is "ARIP saw 200 traces and found no anomaly
  pattern worth reporting; that is the answer."
- The single abstention cluster is descriptive ("ARIP doesn't know
  about this shape"), not pejorative.

**Operator-honest framing:** *"No surprises here. ARIP looked at
your normal traffic and didn't invent a problem. That's
working-as-designed."*

If the operator was hoping for "and here are the anomalies you don't
know about", reset expectations: observe-mode reports the engine's
verdicts on the engine's existing rules. Anomalies *outside* those
rules don't surface as anomalies, they surface as recurring
`no_rule_matched` abstentions.

---

## Example D — Low-quality-telemetry pilot digest

What this looks like: 25 orphan-span traces (parent_span_id
references spans not in the bundle — common with tail sampling
where the parent batch wasn't sampled).

```markdown
# ARIP observation digest

## Run summary

- source: jsonl:///private/tmp/orphans.jsonl
- traces observed: 25
- new events: 25
- quality band distribution: medium=25
- rule matches: <none>
- abstentions: weak_evidence=25

## Recurring patterns (rule-grounded)

_No rule-grounded recurring patterns in this window._

## Recurring abstentions

| abstention    | recurrence | services            | operations          |
|---------------|-----------:|---------------------|---------------------|
| weak_evidence |         25 | inventory-service   | inventory.reserve   |
```

**How to read this with the operator:**

- All 25 traces landed in `weak_evidence`. The engine consistently
  had span signal but no log corroboration, falling below
  `MIN_EVIDENCE_KINDS=2`.
- Quality band is uniformly `medium` — propagation_health drops to
  zero on orphan traces, dragging the score down from `high` even
  though spans are present.
- No rule cluster surfaced — engine declined every observation.

**Operator-honest framing:** *"Your telemetry is structurally
incomplete (orphan spans). ARIP's response is to abstain
consistently rather than guess. The first useful thing to do is fix
the telemetry hygiene — check if log_trace_correlation is working
and why the parent spans are missing."*

This is also a useful pilot signal: it confirms the trust contract
holds under low-quality input. The engine does not invent rule
clusters to fill the silence.

---

## Patterns to look for across examples

| Pattern | Indicates | Action |
|---|---|---|
| Few clusters, high recurrence per cluster | Healthy telemetry + real anomaly patterns | Operator can act on cluster's "where to look" pointer |
| Many singleton clusters | High-cardinality fingerprint (regression of validation fix) | Stop pilot; check `clustering.py` |
| Only abstention clusters | Either healthy traffic or low-quality telemetry | Compare quality_band distribution to decide which |
| Uniformly medium / low band | Telemetry-hygiene issue | Fix telemetry, then re-pilot |
| Empty digest | No traces ingested | Check source path and adapter output |

If the digest doesn't match one of these patterns cleanly, capture
it in `usability-findings.md` as a "shape we didn't anticipate" —
that's a candidate for the next docs pass.
