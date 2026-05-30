# Telemetry hygiene audit report — `[CUSTOMER NAME]`

**Audit date:** `[YYYY-MM-DD]`
**Auditor:** `[Your Name]`
**Customer engineering contact:** `[Name, Title]`
**Telemetry sample:** `[1-hour window starting YYYY-MM-DD HH:MM, N traces, source: Jaeger/Tempo/Elasticsearch]`

> Template — Offering B deliverable. Fill in `[BRACKETED]` sections
> with real data from the customer's telemetry. Honest framing: this
> report is valuable EVEN IF the customer decides not to roll out
> ARIP, because the findings stand independently.

---

## TL;DR

`[1-2 paragraph summary of the customer's telemetry hygiene state.
Honest. Examples:]`

> Customer's distributed tracing is well-configured at the service
> level but has 2 systemic gaps that prevent ARIP from being
> immediately useful: (a) the `payment-service` doesn't emit OTel
> traces, so trace chains break at that boundary; (b) logs from
> `inventory-service` lack the `trace_id` MDC field, so they can't
> be correlated with spans. Both fixes are low-effort (estimated
> total: 2-4 engineering days). After both, ARIP would be ready
> to investigate `[N]`% of the failure patterns we sampled.

OR:

> Customer's telemetry is in better shape than expected. All 5 ARIP
> rules have the signals they need, log correlation works for the
> services that matter, and business-key propagation chains are
> intact across all sampled flows. The single material gap is
> `[X]`. ARIP would be useful with minimal preparation.

OR:

> Customer's current telemetry is not ready for ARIP. The
> prerequisite gate failed `[reason]`. Three options: (1) add
> OTel distributed tracing (~6-8 weeks effort, separate
> engagement); (2) use ARIP only for the parts of the system that
> ARE traced (~30% of services); (3) ARIP is not the right tool
> for this stack.

## 1. Methodology

This audit ran ARIP's deterministic prerequisite gate, quality
assessment, and hygiene findings against a 1-hour sample of
Customer's `[telemetry backend]` telemetry. The sample contained
`[N]` traces across `[M]` services.

No production systems were modified. No data left Customer's
environment (audit run on a Provider-controlled machine with a
Customer-provided telemetry export OR run in Customer's
environment with read-only credentials).

The audit checks 5 categories, each rooted in what ARIP's engine
needs to function:

1. **Distributed tracing baseline** — can ARIP run at all?
2. **Span tree propagation** — does the trace structure hold across
   services?
3. **Service coverage** — are all expected services contributing
   spans?
4. **Log–trace correlation** — can logs be joined to traces?
5. **Business-key propagation** — does the entity ID survive across
   service boundaries?

## 2. Distributed tracing baseline

Status: `[PASS / FAIL]`

**Findings:**

`[For each: PASS or FAIL with specific evidence]`

| Check | Status | Evidence |
|---|---|---|
| ≥ 1 span per trace | `[PASS / FAIL]` | `[N traces sampled, M had spans]` |
| Each span carries `trace_id` | `[PASS / FAIL]` | `[100% / 87% / etc.]` |
| ≥ 2 services per trace OR parent_span_id chain present | `[PASS / FAIL]` | `[average of N services/trace; M% have parent chains]` |

**Interpretation:**

`[If PASS:]`
Customer's telemetry passes the baseline. ARIP's prerequisite
gate would not block. Proceed to subsequent sections.

`[If FAIL on any check:]`
Customer's telemetry fails the baseline. ARIP's prerequisite gate
would refuse to run with the following message:

```
[Paste the actual PrerequisiteFailure.detail + next_step from running
arip preflight against the sample]
```

**This is a stop-the-line finding.** Until this is addressed, ARIP
cannot meaningfully investigate Customer's failures. See
"Recommended actions" below.

## 3. Span tree propagation

`[Run ARIP's hygiene findings against the sample. Report the
specific orphan-span findings:]`

**Orphan span count:** `[N]` orphan spans across `[M]` traces
(`[X]`% of total spans).

**Services responsible for orphan spans:**

| Service | Orphan span count | Likely cause |
|---|---|---|
| `[service-A]` | `[N]` | `[upstream not OTel-instrumented / API gateway strips headers / other]` |
| `[service-B]` | `[N]` | `[...]` |

**Interpretation:**

`[If orphan count is low (< 5%):]`
Span tree propagation is healthy. Minor orphans are normal under
tail sampling. No action required.

`[If orphan count is moderate (5-20%):]`
There's a systematic propagation gap. Most likely cause based on
the service distribution: `[diagnosis]`. Recommended fix: `[specific
action — e.g., "configure traceparent header forwarding on the
nginx ingress at the platform team level"]`.

`[If orphan count is high (> 20%):]`
Trace propagation is broken at one or more service boundaries.
ARIP would systematically miss cross-service evidence, leading
to elevated `weak_evidence` abstentions. This must be fixed
before ARIP can be effective.

## 4. Service coverage

**Services emitting traces in this sample:**

`[List all services that appeared in the sample]`

- `[service-1]`: `[N]` traces, `[M]` total spans
- `[service-2]`: `[N]` traces, `[M]` total spans
- ...

**Services explicitly checked against expectation:**

`[If Customer provided an "expected_services_per_trace" list:]`

| Expected | Present? | Notes |
|---|---|---|
| `frontend` | ✓ | 87 traces |
| `cart-service` | ✓ | 87 traces |
| `payment-service` | ✗ | **Missing — no spans found** |
| `inventory-service` | ✓ | 81 traces |

**Critical missing services:**

`[For each missing service, write 1-2 sentences:]`

- **`payment-service`**: Not present in any trace despite being in
  the expected flow. Likely cause: `[no OTel SDK installed /
  sampler set to 0 / collector not configured]`. Without payment
  spans, ARIP cannot investigate payment-related failures.

## 5. Log–trace correlation

**Log entries in sample:** `[N]` (from Loki / Elasticsearch query
over the same time window)

**Logs carrying `trace_id`:** `[M]` (`[X]`% of total)

**Per-service log–trace correlation:**

| Service | Log entries | With trace_id | Coverage |
|---|---|---|---|
| `frontend` | 1,234 | 1,210 | 98% |
| `cart-service` | 567 | 540 | 95% |
| `payment-service` | 234 | 12 | **5%** |
| `inventory-service` | 891 | 845 | 95% |

**Interpretation:**

`[If overall coverage is high (> 90%):]`
Log–trace correlation works. ARIP's `MIN_EVIDENCE_KINDS=2` gate
will be satisfied for most rule-grounded clusters. No action
required at the platform level.

`[If overall coverage is mixed or low:]`
Log–trace correlation is broken for the services listed in red
above. Without correlated logs, ARIP will frequently hit
`weak_evidence` abstentions on traces from these services — the
engine has the span evidence but can't promote a primary
hypothesis without supporting log evidence.

**Specific service-level fixes:**

- **`payment-service`**: 5% log–trace correlation. Likely cause:
  logger MDC (Mapped Diagnostic Context) doesn't include
  `trace_id`. Fix: add OTel logging integration to the service's
  logger config. Effort: ~half day for one Java developer
  (assuming Spring Boot + Logback).

## 6. Business-key propagation

**Configured business key(s):** `[order.id / account_id / etc.]`

**Sample analysis:**

Of `[N]` traces sampled, `[M]` had an entry-point span carrying the
business key. Of those:
- `[X]` had the key propagated to ≥ 1 downstream span (`[Y]`%)
- `[Z]` did not propagate the key (`[W]`%)

**Cross-trace correlation feasibility:**

`[If propagation is high:]`
Cross-trace correlation via business key would work. ARIP's
`concurrent_modification` rule would be functional.

`[If propagation is low:]`
Cross-trace correlation is broken for `[X]`% of requests. ARIP
will miss sibling-trace patterns (e.g., webhook race conditions,
async-event flows). To fix: ensure downstream services include
the business key in their span attributes.

**ID translation chains observed (if any):**

`[If the customer's system renames the key across services, list
the chain. Otherwise note "no ID translation detected — single
key spelling used consistently".]`

> Example: `order_id` on `frontend` → `payment.order_ref` on
> `payment-service` → `shipment.order_no` on `shipping-service`.
> ARIP's `business_key_aliases` config can handle this — see
> recommendation in Section 8.

## 7. Rule readiness assessment

For each of ARIP's 5 rules, would the telemetry in this sample let
it fire correctly?

| Rule | Required signals | Customer telemetry has | Verdict |
|---|---|---|---|
| `retry_storm` | `retry.attempt`, `retry.backoff_ms`, `retry.reason` | `[YES/NO/PARTIAL — list specifics]` | `[Ready / Needs work / Won't fire]` |
| `db_pool_exhaustion` | `db.pool.acquired`, `db.pool.max`, `db.pool.wait_ms` | `[...]` | `[...]` |
| `downstream_error` | ERROR status crossing service boundary | `[...]` | `[...]` |
| `concurrent_modification` | Business key + `state.transition` events | `[...]` | `[...]` |
| `latency_vs_db` | Handler operation pattern + `db.system` attr | `[...]` | `[...]` |

**Summary:** `[X]` of 5 rules would fire on this telemetry as-is.
`[Y]` would fire after the fixes in Section 8.

## 8. Recommended actions, prioritized

`[Numbered list of specific telemetry-hygiene fixes, ordered by
effort/value ratio. Each item: what to do, who likely owns it,
estimated effort, what it unlocks.]`

1. **`[Highest priority]` Add OTel SDK to `payment-service`.**
   - Owner: payment team
   - Effort: 1-2 days
   - Unlocks: `downstream_error` rule on payment flows; closes
     the service-coverage gap

2. **`[Second]` Add `trace_id` to `inventory-service` Logback MDC.**
   - Owner: inventory team
   - Effort: 0.5 days
   - Unlocks: log evidence for traces involving inventory →
     fewer `weak_evidence` abstentions

3. **`[Third]` Configure traceparent forwarding on nginx ingress.**
   - Owner: platform team
   - Effort: 0.5 days
   - Unlocks: fixes ~80% of the orphan-span findings; healthier
     span tree across the board

4. **`[Fourth, if applicable]` Add `business_key_aliases` to ARIP
   config to handle ID translation.**
   - Owner: ARIP operator (you, in a follow-on engagement)
   - Effort: 1 hour
   - Unlocks: cross-trace correlation through the
     `order.id → payment.order_ref → shipment.order_no` chain

## 9. ARIP fit assessment

**Overall:** `[GOOD / MIXED / POOR]` fit for this telemetry.

`[Honest 1-2 paragraph summary]`

Examples:

> GOOD: After the 4 fixes in Section 8 (total effort ~3 engineering
> days), ARIP would be ready to investigate Customer's failures
> with `[X]` of 5 rules functional. Estimated rule coverage of
> failure patterns we sampled: `[Y]`%. Recommended next step:
> proceed to the integration engagement (Offering A).

> MIXED: ARIP would be partially functional. 2 of 5 rules
> (`downstream_error` and `latency_vs_db`) would fire on existing
> telemetry. The other 3 require telemetry investments
> (retry metadata, business keys, state transitions) that may or
> may not be worth it depending on how often Customer hits those
> failure patterns. Recommend a 30-min follow-up call to discuss
> whether the additional investment is justified.

> POOR: Customer's telemetry is not ARIP-ready and the fixes
> required (full OTel rollout, ~6-8 weeks of platform work) are
> not justified solely by ARIP's value. ARIP is not the right
> tool for this stack at this time. Recommend revisiting in 6-12
> months after the platform team's OTel rollout, OR considering
> a different category of tool (e.g., logs-based analytics like
> Honeycomb or Datadog as a first step).

## 10. What this audit did NOT do

For transparency:

- Did not modify any Customer system or telemetry config
- Did not look at Customer source code (only at telemetry output)
- Did not assess Customer's APM / monitoring stack beyond what's
  visible in the sample
- Did not compare ARIP against other tools — only assessed
  fitness for ARIP
- Did not consider performance / scale aspects — sample-only
- Did not look at production incidents beyond the sample window

If any of these would be valuable, separate engagement.

## 11. Appendix — raw telemetry stats

**Sample window:** `[start — end, duration]`
**Trace count:** `[N]`
**Span count:** `[M]`
**Service count:** `[K]`
**Log entry count:** `[L]`

**Quality band distribution (from `arip preflight`):**

| Band | Count | % |
|---|---|---|
| high | `[N]` | `[%]` |
| medium | `[N]` | `[%]` |
| low | `[N]` | `[%]` |

**Raw `arip preflight` output:** See attached `preflight-output.txt`

**Raw observe digest:** See attached `observe-digest.md`

---

`[End of audit report]`

---

## Operator notes (delete before sending to customer)

**Time to produce:** 4-6 hours of analysis + 1-2 hours of writing.

**What makes this report valuable beyond ARIP:**
The findings stand even if customer never uses ARIP. The hygiene
checks (propagation, log correlation, business-key chain) are
fundamentally good distributed-tracing practices. Many customers
will say "this report alone is worth what we paid".

**Common mistakes to avoid:**
- Don't soft-pedal failures. If their telemetry isn't ready, say
  it clearly. POOR fit verdict is OK to deliver.
- Don't recommend ARIP if the fit is genuinely poor — refer them
  to telemetry-hygiene services first.
- Don't add findings that aren't grounded in the sample. Every
  claim must be traceable to a specific trace/log in the data.

**Pricing leverage:**
A good audit report can be the entire basis for a $20-50k
follow-on engagement (telemetry hygiene work + ARIP integration).
The $3-8k for the audit is the introduction, not the destination.
