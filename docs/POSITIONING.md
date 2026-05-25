# Positioning

**This is an engineering strategy document, not marketing copy.** It
exists to gate roadmap decisions. Before merging anything that
expands scope, ask: *"Does this strengthen the positioning, or does
it pull ARIP toward a category it should not enter?"*

If the answer is the second, the change does not ship — even if it is
technically interesting.

## What ARIP is

**Product framing:** **deterministic CI investigation engine.**
Triggered by a CI test failure, produces a single evidence-grounded
post-mortem report, surfaced where the engineer already lives (a PR
comment). Five rules. No LLM in the analysis path. Says "I don't
know" when the signal does not justify a hypothesis.

**Technical framing:** **deterministic, trust-aware reasoning layer
over already-collected telemetry.** It reads from Jaeger / Tempo /
Loki / docker-logs and produces structured `Hypothesis` records
with cited `Evidence`. The reasoning layer is what differentiates
ARIP; the substrate is whatever the customer already has.

Use the product framing when talking to humans. The technical framing
is for documents like this one.

## What ARIP is NOT (anti-goals)

These are **load-bearing constraints.** Each one rules out an entire
adjacent category that ARIP could otherwise drift into.

| ARIP is NOT…             | Why                                                                                                    |
|---------------------------|--------------------------------------------------------------------------------------------------------|
| a telemetry collector     | OpenTelemetry already covers emission. ARIP **consumes** OTel; never re-implements it.                 |
| a storage backend         | Jaeger, Tempo, Loki, ClickHouse already cover storage. ARIP holds a SQLite memory for fingerprints — that is **not** a database product. |
| a dashboard               | Grafana already covers visualisation. ARIP's UI is *markdown*; that is a deliberate ceiling, not a stepping stone. |
| an APM                    | APM is real-time monitoring + alerting. ARIP is **post-failure**, **read-only**, **batch**.            |
| an incident-response tool | PagerDuty / FireHydrant cover that. ARIP does not page, escalate, or run runbooks.                     |
| an autonomous agent       | The name *Autonomous Reliability Investigation Platform* is contentious — ARIP does not **act**, it reports. (Naming refresh under consideration.) |
| an AI hype tool           | The LLM is optional, never sees raw telemetry, never introduces new claims, and is fully replaceable by a deterministic fallback. |
| a generic logging platform | Splunk / Elastic cover that. ARIP **reads** logs to ground evidence; it never indexes them.            |

Each of these anti-goals is also a competitive non-aggression pact.
Becoming any one of them puts ARIP into direct competition with
incumbents that have a 10–20 year head start and orders of magnitude
more capital. **The category is "deterministic CI investigation
engine" and only that.**

## Where ARIP sits in the stack

```
┌─────────────────────────────────────────┐
│  Engineer / PR / Slack                  │  ← workflow surface
├─────────────────────────────────────────┤
│  ARIP — deterministic investigation     │  ← our layer
├─────────────────────────────────────────┤
│  Jaeger · Loki · Prometheus · K8s API   │  ← upstream telemetry
├─────────────────────────────────────────┤
│  OpenTelemetry SDK + Collector          │  ← emit / collect
├─────────────────────────────────────────┤
│  Application services                   │  ← source of truth
└─────────────────────────────────────────┘
```

ARIP only ever grows **up** (toward workflow integrations) or **across**
(more reasoning power on the same telemetry). It never grows down.

## Ecosystem overlap matrix

| Component                  | What it does                              | ARIP overlap | How we treat it                                                                  |
|----------------------------|-------------------------------------------|--------------|----------------------------------------------------------------------------------|
| **OpenTelemetry**          | Emission spec + SDKs                      | 0%           | **Upstream**. Consume OTel-spec telemetry. Never re-implement.                   |
| **Jaeger / Tempo**         | Trace storage + UI                        | 0%           | **Upstream**. `JaegerClient` reads from `/api/traces/<id>`.                      |
| **Loki / Elasticsearch**   | Log storage + search                      | 0%           | **Upstream**. Demo uses docker logs; production: swap for Loki client.           |
| **Prometheus / Grafana**   | Metrics + dashboards                      | 0%           | **Upstream**. ARIP reports can deep-link to a Grafana panel; never replace it.   |
| **Datadog (Watchdog)**     | AI-driven anomaly + RCA                   | 30–50%       | **Same problem space, opposite philosophy.** Datadog: ML inference. ARIP: deterministic rules + abstention. |
| **Dynatrace (Davis)**      | Same as Datadog                           | 30–50%       | Same. |
| **Honeycomb (BubbleUp)**   | High-cardinality anomaly slicing          | 20–30%       | **Partial.** Honeycomb is investigative but dashboard-first. ARIP is PR-first. |
| **Splunk / Elastic**       | Log query platforms                       | 0%           | **Upstream**. |
| **Robusta / k8sgpt**       | K8s incident analysis (some AI)           | ~10%         | **Adjacent**, different surface (k8s events vs test failures). |
| **Replay.io / Antithesis** | Deterministic reproduction / replay       | 0%           | **Adjacent** but a different problem. See [FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md) Phase 4. |

The only real competitive overlap is with the **AI-RCA features of
the big APM vendors**. We do not compete on telemetry breadth (they
win that). We compete on **reasoning honesty**.

## The moat — why the big vendors structurally can't copy us

Four properties combine into a defensible position:

1. **Deterministic reasoning.** Same telemetry → same conclusion,
   byte-identical. Auditable, reproducible. Vendors selling
   "AI-discovered root causes" cannot adopt this because it
   contradicts their differentiation pitch.
2. **Abstention discipline.** ARIP refuses to nominate a primary
   hypothesis when signals conflict below the trust ceiling.
   Vendors structurally cannot ship "I don't know" — investor decks
   require confidence.
3. **Evidence audit.** Every cited `span_id` / log line must exist
   in the live telemetry, or the engine drops it and decays
   confidence. This is the property auditability / compliance teams
   increasingly demand.
4. **Public calibration benchmark.** The `flaky_dependency`
   scenario in [CALIBRATION.md](CALIBRATION.md) and the 10 cases in
   [calibration-gallery.md](calibration-gallery.md) are
   reproducible counter-examples to "AI RCA" — published, in code,
   in `tests/test_calibration_benchmark.py`. No vendor publishes a
   benchmark that could embarrass their AI.

**The combination is the moat, not any individual item.** A vendor
could in principle adopt any one of these; adopting all four would
gut their existing sales narrative. That is what makes the position
defensible.

## Primary integration surface: PR-native

ARIP's workflow position is **the PR comment**. Not a dashboard, not
a Slack bot (yet), not an email alert — the place an engineer
already opens, in the context of code they already changed.

This is non-obvious and worth repeating: **the integration matters as
much as the engine.** A perfect engine output ignored in a separate
tool is worth less than a 90% engine output sitting next to the
"Files changed" tab.

Why PR-native wins:

- The engineer is already there (existing workflow).
- Sticky comment dedup means re-runs update in place — no thread spam.
- The PR provides natural persistence: open → merged → closed.
- The relationship between failure and code change is direct.
- No second tool to evaluate, deploy, or maintain.

**Decision:** PR-native is a load-bearing decision. Roadmap items
that pull primary investigation away from the PR comment are
rejected.

Acceptable extensions of the PR-native surface:
- Concise comment + linked full report in artifact (already shipped)
- PR description suggestion (one-line summary in the PR body)
- PR check status (red/yellow/green from ARIP)
- PR label suggestion (e.g. `flaky-test` if the test is classified flaky)

Unacceptable extensions:
- A separate dashboard that competes with the PR for attention
- Notifications that imply the PR is not enough
- Multi-tenant SaaS UI

## Integration roadmap — engineering workflow impact

| Integration                             | Impact   | Friction   | When                       |
|------------------------------------------|----------|------------|----------------------------|
| **GitHub Actions + PR sticky comment**   | ★★★★★ | low (shipped) | **now — go deeper**        |
| **Jaeger / Tempo deep-link in PR**        | ★★★    | config     | now                        |
| **Grafana panel deep-link**               | ★★★    | config     | Phase 2                    |
| **GitLab CI + Merge Request comment**     | ★★★★  | low (port) | Phase 2                    |
| **Jenkins**                               | ★★      | high (groovy) | only on pilot pull       |
| **ArgoCD rollout correlation**            | ★★★★  | high (k8s) | Phase 3, needs k8s         |
| **Slack summary bot**                     | ★★      | low        | post-pilot; dilutes PR-first  |
| **Jira auto-create**                      | ★        | low        | **decline** — workflow noise   |
| **PagerDuty hand-off**                    | ★        | low        | **decline** — not incident response |

## Kubernetes — strategic fit, deferred

K8s integration is **maturity-2**, not now. The natural fit points,
in approximate value order:

1. **OOMKilled / ContainerCannotRun events** correlated with the
   failing trace's time window. High-signal evidence; could become
   an `Evidence(kind="k8s_event")` line in existing reports.
2. **Rollout correlation** (ArgoCD / Flux) — a test failure that
   coincides with a recent deploy is strong evidence for a
   regression. This *could* become a new rule but only after pilot
   data demonstrates demand.
3. **Service mesh (Istio / Linkerd) L7 spans** — additional
   visibility into network-layer retries / timeouts the app SDK
   doesn't see.
4. **Readiness / liveness probe failures** — k8s events as
   corroborating signal.

**Decision:** do not add Kubernetes telemetry support until at
least two pilots demonstrate they would have used it. Anything
sooner is speculation.

## Long-term direction

Four candidate paths, with verdicts:

| Path                                                | Verdict             | Reason                                                                 |
|------------------------------------------------------|---------------------|------------------------------------------------------------------------|
| (A) General AI observability platform                | 🚫 do not pursue    | Massive capital, direct vendor competition, AI hype contradicts the moat. |
| (B) **Deterministic CI/CD investigation engine**     | ✅ current position | Narrow scope, concrete buyer, demonstrable value, defensible moat.    |
| (C) Trust-aware telemetry reasoning layer            | ⏳ Phase 2-3 framing| Correct technically but too abstract to sell today. Earn it via pilots. |
| (D) QA/SDET investigation assistant                  | 🚫 too narrow       | QA niche ~10–15% of TAM; engineer buyer is bigger. Treat as a sub-segment of B, not its own product. |

**Trajectory:** B today, evolve to C over 2–3 years as the pilot
base grows and the language of "telemetry reasoning" becomes
mainstream. **Never A.** D is acknowledged as a strong sub-segment
of B (Playwright + Cypress users are predominantly QA-adjacent) but
not a standalone direction.

## Pilot profile — the right first three customers

**Engineer profile:** Platform engineer / SDET / backend lead who
*owns* CI flakiness pain. Senior IC or engineering manager.
**AI-skeptical** is a strong positive — they will value calibration.

**Company profile:**
- 50–300 engineers (smaller → not enough usage; larger → procurement-bound)
- Already adopted OpenTelemetry (non-negotiable)
- Playwright or Cypress in CI
- GitHub Actions (because PR comment is the killer surface)
- Active PR review culture (≥ 10 PRs / week)

**Repo profile:**
- 5–50 microservices
- OTel auto-instrumentation in use
- Test flakiness is a known team pain point

**Telemetry quality:**
- **Medium**, not pristine. Pristine telemetry hides ARIP's
  abstention pathway; messy telemetry is where the calibration
  layer earns trust.

**Anti-pilots:**
- 1000+ engineer enterprise (procurement bottleneck)
- No OTel (re-instrumentation pilot cost is fatal)
- Pre-product startup (CI isn't mature)
- "Replace Datadog" expectation (positioning mismatch)
- SaaS-only buyer (not yet)

## Success metric evolution

| Phase           | Question                              | Metric                                                              | Threshold              |
|-----------------|---------------------------------------|---------------------------------------------------------------------|------------------------|
| 0 (✓ shipped)    | "Does it work?"                       | Demo pipeline runs end-to-end < 60 s                                | ≤ 16 s actual          |
| 1 (active)      | "Does an engineer trust it?"          | Pilot feedback says "this was actually useful"                       | ≥ 3 pilots pass        |
| 2               | "Does it accelerate workflow?"        | Investigation time saved (manual vs ARIP-assisted, median minutes)   | ≥ 5× speedup            |
| 2               | "Is it precise enough?"               | **False-high-confidence rate** (primary nominated, was wrong)        | **< 5%** — release-gate |
| 2               | "Is abstention useful?"               | When ARIP abstains, the failure WAS ambiguous                        | ≥ 80% useful           |
| 3               | "Does trust persist?"                 | NPS-equivalent after N > 100 investigations                          | ≥ +30                  |
| 3               | "Is onboarding viable?"               | Clone → first useful PR comment                                       | < 4 hours              |
| 3               | "Does the memory layer work?"         | Cross-run "seen N times" notification correct                         | ≥ 90% accuracy         |

**The single most important metric is false-high-confidence rate.**
If it exceeds 10% in any pilot, the trust contract has cracked and
shipping pauses until it is restored. Coverage can drop; trust may not.

## How to use this document — the gate

When considering any new feature, scenario, rule, or integration,
walk through these questions:

1. Does this change pull ARIP toward an anti-goal? (Section "What
   ARIP is NOT.") If yes → **reject**.
2. Does this change introduce uncertainty that the abstention layer
   cannot detect? If yes → **reject** or extend abstention first.
3. Does this change require ARIP to be a telemetry collector, a
   storage backend, a dashboard, or a UI platform? If yes → **reject**.
4. Could this change cause a confident-but-wrong RCA in any
   calibration benchmark scenario? If yes → **reject** until the
   benchmark stays green.
5. Does this change strengthen the **PR-native primary surface**? If
   no → re-justify; the surface is load-bearing.
6. Does this change strengthen the **moat** (determinism, abstention,
   evidence audit, calibration)? If no → consider scope-creep risk.
7. Does this change move ARIP toward direction **B** (CI engine) or
   toward direction **A** (general AI observability)? If A → reject.

If all seven gates pass, the change is in scope. If even one fails,
write down which one and either close the PR or strengthen the
proposal until the gate passes.

## Related documents

- [PILOT.md](../PILOT.md) — pilot kit; uses this positioning to scope what to test
- [ROADMAP.md](../ROADMAP.md) — phased plan, each phase consistent with positioning
- [CALIBRATION.md](CALIBRATION.md) — the trust contract this positioning depends on
- [ONBOARDING.md](ONBOARDING.md) — the config-driven portability that makes the position viable
- [FUTURE_ARCHITECTURE.md](FUTURE_ARCHITECTURE.md) — items deferred *because* of this positioning, with triggers for re-evaluation

## Revision discipline

This document is updated **only** in response to pilot evidence, not
speculation. A revision must cite:

- which pilot session prompted the change (with date and pilot ID), or
- which calibration benchmark scenario broke or was added, or
- which ecosystem event (a vendor announcement, OTel spec change)
  invalidates a prior claim.

Revisions without one of those citations are scope creep. Reject.
