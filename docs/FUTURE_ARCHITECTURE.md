# Future Architecture Notes

Items that are **explicitly deferred** in the current MVP. They are not
under-built — they are deliberately not built. The MVP targets a
Playwright/GitHub-Actions niche; the items below are the architectural
upgrades a credible "next-generation investigation platform" would
require to scale beyond that niche.

Each section captures:

- **What:** the capability
- **Why deferred:** the pragmatic reason it isn't in MVP
- **Trigger:** the signal that would justify building it
- **Sketch:** a rough implementation path so future-us doesn't start
  from zero

---

## 1. Deterministic replay

**What.** Capture enough information at run-time to deterministically
re-execute a failed request offline — same scheduler interleavings,
same DB state, same external responses.

**Why deferred.** True deterministic replay is hypervisor- or
language-runtime-level work (Antithesis, rr, Replay.io). It's a multi-
engineer-year investment. MVP customers don't need it; they need a
report that tells them where to look.

**Trigger.** A customer pays meaningfully more for "open the failure
in a time-travel debugger" than for "read a markdown report".

**Sketch.** Browser side: ship Playwright `trace.zip` next to the
ARIP report (already supported by Playwright). Backend side:
record HTTP request + response pairs and DB query + result pairs
via OTel attributes large enough to replay against a clean staging
deployment. No language-runtime determinism — partial replay only.

---

## 2. Causal inference (vs correlation)

**What.** Distinguish "trace A *caused* failure in trace B" from
"trace A and B are correlated in time and share a business key".

**Why deferred.** Real causality in distributed systems needs vector
clocks / Lamport timestamps / OTel `Link`s emitted by every async
boundary. Most apps don't emit them. Without them, correlation is
the best inference available.

**Trigger.** A customer's failures are systematically misdiagnosed
by the engine because two unrelated operations happen to share an
`order.id` and overlap in time.

**Sketch.** Require producers (Kafka, message bus clients) to emit
OTel span links to the message origin. Add a `LinksAwareRule`
class that traverses links instead of timing windows. Until then,
keep abstaining on "weak evidence" rather than fabricating causal
claims (already implemented).

---

## 3. eBPF / kernel-level telemetry

**What.** Capture TCP retransmits, DNS resolution failures, cgroup
throttling, OOMKill events, syscall-level latency — signals invisible
to application-level OTel.

**Why deferred.** Requires Cilium/Hubble / Tetragon / Pixie
infrastructure. Out of scope for a Playwright-focused MVP.

**Trigger.** A class of failures the rules consistently abstain on,
where the root cause turns out to be network/infra-level.

**Sketch.** A new correlator client `ebpf_client.py` that pulls
Hubble flow events for the failure's pod/node window. A new
`NetworkFailureRule` that joins OTel span errors with Hubble flows
to attribute "connection refused" to the right side.

---

## 4. Service dependency graph + blast radius

**What.** A persistent graph of which services call which, with
versioning. Used to compute blast radius and identify "the failure
that took down 7 services has its origin in service X".

**Why deferred.** Bizim MVP zaten span tree'den lokal yapı çıkarıyor.
Cross-trace global graph "iyi olur" ama satılabilir bir feature
değil tek başına.

**Trigger.** A customer with >20 services where local-tree reasoning
keeps missing the upstream root cause.

**Sketch.** Nightly batch job that scans Jaeger for all observed
edges (caller_service, callee_service, operation) and writes to a
Postgres graph table. A `GraphAwareRule` consults this when
walking error chains. Decay edges over time; rebuild weekly.

---

## 5. Multi-agent investigation workflows

**What.** Multiple specialist agents (trace-agent, log-agent,
hypothesis-agent) that can request more data, hypothesise, refine,
and converge.

**Why deferred.** Yields a much larger surface for hallucination
(the original complaint that drove our deterministic refactor).
Current single-pipeline approach is more honest and faster.

**Trigger.** Customers ask "why didn't the engine consider hypothesis
X?" enough that we need an open-ended investigation loop, not just
fixed rules.

**Sketch.** Each rule becomes an agent with `query(ct, hint) -> Hypothesis | NeedMoreData`.
A coordinator routes `NeedMoreData` requests to the correlator
(fetch more logs, fetch sibling traces) and re-runs. Bounded
iterations + bounded telemetry budget. All claims must still be
deterministic-rule-grounded; agents propose, rules dispose.

---

## 6. Statistical anomaly baselines

**What.** Per-endpoint p50/p99/error-rate baselines so rules say
"this is 8σ above normal" instead of "this exceeds 50ms".

**Why deferred.** Needs a learning period (days to weeks) per
deployment. MVP wants to be useful from minute zero.

**Trigger.** Latency rule false-positives or false-negatives on
customer traffic.

**Sketch.** A `baselines/` package that reads daily from Jaeger,
computes per-(service, operation, hour-of-day) p50/p99/error-rate,
stores in the same SQLite as memory. Rules consult it for thresholds.

---

## 7. Cross-trace causality via OTel Links

**What.** When a Kafka consumer processes a message, its span has a
`Link` to the producer's span. Across-process happens-before in OTel.

**Why deferred.** Demo stack has no async/event-driven communication.
Adding it just to have it is premature; we'd be building a substrate
for a rule we don't need yet.

**Trigger.** First customer scenario where async boundaries are the
failure mode (Kafka consumer crash, SNS retries, etc.).

**Sketch.** Producer instrumentation: every event publish creates a
span that emits a `traceparent` field into the message header. Consumer
instrumentation: extracts that, starts a span with a Link to it. The
correlator gains an "include linked spans" mode for trace traversal.

---

## 8. Privacy / PII redaction

**What.** Logs and trace attributes routinely contain PII (emails,
addresses, tokens). MVP stores them as-is; production cannot.

**Why deferred.** Demo data has no PII.

**Trigger.** Any customer pilot.

**Sketch.** A redaction step in the correlator: regex-based PII
patterns + key-name allowlist (e.g. only keep `order.id`,
`http.method`, drop everything else). Pluggable per customer.

---

## 9. Regression test generation

**What.** From an investigation report, synthesise a runnable test
that would catch the same failure on a future run.

**Why deferred.** Genuinely hard. Requires understanding test
framework, fixtures, and what assertion would have caught the bug.
Easy to get wrong; embarrassing when wrong.

**Trigger.** Customer feedback that the report tells them *what*
but not *how to prevent regression*.

**Sketch.** Start small — emit a snippet (curl + expected status)
that reproduces the failing request from the trace, not a full
test. Let humans wrap it into their test framework. Iterate.

---

## 10. Confidence calibration

**What.** A meta-loop that records "rule X claimed 0.9 confidence;
ground-truth said it was right 60% of the time" and adjusts.

**Why deferred.** Needs feedback labels we don't yet collect.

**Trigger.** Calibrated confidence is what makes confidence numbers
honest. We need labelled outcomes (customer marks reports
correct/incorrect) to build it.

**Sketch.** PR comment includes 👍/👎 reactions. Action ingests
them as labels into the memory store. Periodic batch recomputes
rule-level confidence priors. Display "1247 cases, 0.92 historical
accuracy" alongside per-investigation confidence.

---

## 11. Telemetry-informed reproduction assistance

**What.** Telemetry-informed regression authoring assistance for QA /
test engineers. Production-style telemetry feeds the existing
deterministic engine; recurring anomaly patterns become rule-grounded
clusters; for sufficiently-recurrent clusters, ARIP drafts a
**reproduction candidate** — a parameterised test scenario that
exercises the conditions evidence-aligned with the observed anomaly.

The candidate is **not** a confirmed root cause, **not** a fix
verification, **not** a proof. It is a starting point for an engineer
to author a real regression test in less time than starting from
scratch.

**Why deferred (in part).** The pieces have different cost profiles
and different trust risks. Phase A (observation) is cheap to ship and
preserves the trust contract by reusing the existing engine path.
Phases B–D (cluster narrative → candidate generation → sandbox
validation) each carry meaningful new surface area for false
confidence and must clear independent triggers.

**Status.**

- ✓ **Phase A — Observation** (shipped): `arip observe` produces
  rule-grounded and abstention-grounded clusters from incremental,
  read-only telemetry sources. See
  [docs/OBSERVE_MODE.md](OBSERVE_MODE.md). No candidate generation,
  no PRs, no sandbox runner.
- ☐ **Phase B — Cluster narrative**: a rule-grounded markdown
  narrative for high-recurrence clusters (still text-only, no test
  artifact).
- ☐ **Phase C — Candidate generation**: template-driven, deterministic
  reproduction-candidate test files with strict sanitization,
  filename suffix + header banner + draft PR contract.
- ☐ **Phase D — Sandbox validation** (optional): wrapper that runs a
  candidate against a sandbox and records exercise verification —
  never run against production.

**Trigger to begin Phase B.**

Phase 2 entry gate in [ROADMAP.md](../ROADMAP.md) cleared **AND** ≥ 3
pilot post-mortem entries verbatim state: *"This cluster was useful;
a markdown narrative drafted from it would meaningfully accelerate
my regression authoring"* (or equivalent — captured in
`pilot-archive/<id>/feedback.md`).

**Trigger to begin Phase C.**

Phase B shipped **AND** ≥ 5 pilot entries verbatim state: *"I read
the narrative and started writing a regression test. A draft test
template would have saved meaningful time"*.

**Trigger to begin Phase D.**

Phase C used in ≥ 50% of relevant pilot anomalies **AND** the most
common friction point is "I had to wire up the candidate against my
sandbox myself".

**Non-negotiable trust constraints (all phases).**

- Every candidate carries four lexical markers: filename suffix
  `.candidate.spec.ts`, header banner, PR title prefix
  `[ARIP-CANDIDATE]`, PR body disclaimer.
- Candidate generation is template-driven and deterministic. No LLM
  in the generation path.
- Sanitization is strict: no PII, no exact identifiers, no full
  request bodies, no internal hostnames. Default deny on extracted
  string fields.
- Candidates must abstain on: `insufficient_recurrence`,
  `weak_anomaly_signal`, `unstable_repro_basis`, `unstable_fingerprint`,
  `candidate_template_gap`, `unsafe_signal_extraction`. Each new
  abstention code requires at least one calibration-benchmark
  scenario before shipping.
- Generated PRs are draft-mode and require human checkbox approval.
- Sandbox validation never runs against production.

**Failure mode that closes the capability.**

If the per-pilot reproduction-candidate `misleading_rate` (engineer
reports "this candidate sent me in the wrong direction") exceeds 10%
across a rolling 3-pilot window, Phase C is closed and the capability
returns to Phase B-only until the trust contract is repaired. This
threshold is a release blocker, same class as the false-high-confidence
gate.

**Anti-goal preserved.** This capability does not change ARIP's
identity: not an observability platform, not an autonomous agent, not
an auto-remediation system. It is a QA-assistance layer on top of a
deterministic investigation engine.

---

## 11.5. Cross-trace joining in observe-mode (field-test F5)

`arip observe` currently investigates each trace bundle standalone.
Each bundle becomes one `CorrelatedTelemetry` with `related_trace_ids=[]`,
unlike `arip investigate` mode which uses the `TimelineBuilder` to pull
related traces via business-key lookup.

**Consequence:** the `concurrent_modification` (webhook_race) rule
fundamentally cannot fire on observe-mode data, because the two racing
traces it needs to compare are in separate bundles. Field test
(arip-fieldtest/06-concurrent-modification) confirmed: rule never
matches in observe mode despite a textbook webhook race.

**Trigger to build this:** when an operator running observe-mode reports
"the concurrent_modification rule never fires even though my system has
real races, while `arip investigate` on the same traces catches them."

**Implementation sketch:**
- Index observation events in the SQLite store by business_key value.
- When ingesting a new bundle, query the index for bundles in the last
  `--cross-trace-window` (default: 5min) whose business_key values
  overlap with the current bundle's.
- Join those bundles' spans into the current ct before rule evaluation.
- Cap the join at a per-bundle span budget (e.g. 200 spans) to bound
  memory and rule-evaluation cost.
- Add `--no-cross-trace` flag for operators who explicitly want
  per-bundle isolation.

**Anti-goal protection:** this stays read-only, runs on the same
in-process SQLite store, doesn't pull telemetry from new sources, and
doesn't change rule reasoning — it just extends what's visible to a
single rule invocation.

**Cost:** ~1 day of work + 1 calibration scenario before shipping.

## 12. Generic observability vendor positioning

We are explicitly **not** competing with Honeycomb/Datadog on
generic APM, anomaly detection, dashboarding, log search, or alerting.
We do one narrow thing — investigate test failures end-to-end — and
we leverage whatever telemetry pipeline the customer already has.

This is by design. Re-evaluate if and only if our niche is too small
to support the business; otherwise stay narrow.
