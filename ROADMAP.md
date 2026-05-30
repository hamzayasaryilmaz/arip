# ARIP roadmap

This file is intentionally short. The detailed engineering sketches for
Phase 2 → 4 live in [docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md);
the trigger conditions are the contract.

Things move from a later phase to an earlier phase **only** when there
is a concrete customer reason or technical blocker that makes the
existing scope insufficient. Roadmap drift is harder to undo than slow
deliberate growth.

## Decision gate

**Every roadmap item is gated against [docs/POSITIONING.md](docs/POSITIONING.md).**
Before a change moves from "future" to "in progress" it must clear
all seven gates in that document's *How to use this document* section.
In particular:

- The change must not pull ARIP toward an anti-goal (no telemetry
  collector, no storage backend, no dashboard, no generic APM, no
  autonomous agent, no AI hype tool).
- The change must not introduce uncertainty the abstention layer
  cannot detect.
- The change must strengthen — or at minimum preserve — the
  **PR-native primary surface**.
- The change must strengthen the four-part moat (determinism +
  abstention + evidence audit + calibration benchmark).
- The change must keep ARIP on **Direction B** (deterministic CI
  investigation engine) and not drift toward Direction A (general AI
  observability).

If a proposal cannot pass these gates, it stays in
FUTURE_ARCHITECTURE.md with a documented trigger, or is closed.

## Phase 1 — MVP  ✓ shipped

The credible local-first OSS MVP. The substrate for everything below.

- [x] Deterministic investigation engine — 5 rules, evidence audit, abstention
- [x] Telemetry correlation — Jaeger + Docker logs + DB query attribution
- [x] Cross-run fingerprinting (SQLite memory store)
- [x] Lightweight flaky-test classification
- [x] Tail-based sampling (always-keep errors, slow, force_sample)
- [x] GitHub Actions workflow + sticky PR comments + artifacts
- [x] Five failure patterns:
      `slow_query`, `inventory_error`, `webhook_race`,
      `pool_exhaustion`, `retry_storm`
- [x] Walkthrough docs + curated example artifacts

End-to-end success criterion: Playwright test fails → evidence-backed
markdown report in < 60 s. Measured at 8–16 s locally.

## Phase 2 entry criteria  (gate)

Phase 1 is officially feature-complete. The gate from Phase 1.8 to
**any** Phase 2 work — new rules, new scenarios, new infrastructure,
new abstraction layers, new AI capability — requires ALL of the
following to hold:

- [ ] ≥ 3 independent pilots completed end-to-end per
      [docs/PILOT_RUNBOOK.md](docs/PILOT_RUNBOOK.md)
- [ ] **False-high-confidence rate < 5%** across the rolling 3-pilot
      window (definition: [docs/PILOT_METRICS.md](docs/PILOT_METRICS.md))
- [ ] Onboarding median ≤ 30 minutes (≤ 90 minutes upper bound)
- [ ] Median investigation time saved ≥ 5×
- [ ] At least one pilot engineer said verbatim *"I would actually use
      this on my team"* (or equivalent — captured in `feedback.md`)
- [ ] Zero catastrophic trust failures across the window (no
      `Trust-layer regression` entries in any `outcome.md`)
- [ ] One synthesis run completed per
      [docs/PILOT_SYNTHESIS_TEMPLATE.md](docs/PILOT_SYNTHESIS_TEMPLATE.md);
      its verdict is "Trust contract intact. Continue pilots."

Until all boxes are checked, the default operating mode is
**observe, not build.** New feature ideas stay in
[docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md) with a
trigger condition. Frozen items list below.

## Frozen during Phase 1.8

These items will not move during the pilot window, regardless of how
interesting the proposal is. They reopen only when ≥ 3 pilots have
been completed **and** the synthesis explicitly justifies one of
them with verbatim engineer evidence.

- Deterministic replay / time-travel debugging
- Multi-agent investigation
- Kubernetes operator
- Dashboard UI
- SaaS / hosted control plane
- Auto-remediation
- Full causal inference engine
- eBPF / kernel-level telemetry
- New rules
- New failure scenarios
- New architecture layers (one-time exception: **observation-only**
  Phase A, shipped as a read-only entry point over the existing
  engine — see [Phase A above](#phase-a--observation-mode--shipped-observe-only)
  and [FUTURE_ARCHITECTURE.md item #11](docs/FUTURE_ARCHITECTURE.md))
- New AI capability

If you find yourself wanting to add one of the above mid-pilot, the
correct response is a FUTURE_ARCHITECTURE.md note with the trigger
condition, not a PR.

The Phase A exception above is documented for honesty: it does add a
new module (`arip_core/observation/`), but it does not add new rules,
new failure scenarios, new abstention codes, or new reasoning paths.
It reuses the existing engine end-to-end. The next phases of that
capability (B narrative, C candidate generation, D sandbox) remain
frozen and trigger-gated.

## Phase A — Observation mode  ✓ shipped (observe-only)

A continuous, read-only entry point that runs the existing 5-rule
deterministic engine against production-style trace bundles and
records recurring patterns. Operationalises
[docs/OBSERVE_MODE.md](docs/OBSERVE_MODE.md).

What ships:

- [x] Incremental, cursor-based ingestion (JSONL + JSONL.gz + directory)
- [x] `CanonicalAnomalyEvent` + cluster store (local SQLite, idempotent)
- [x] Rule-grounded **and** abstention-grounded fingerprints (the same
      abstention vocabulary as `arip investigate`)
- [x] Quality-band propagation per event (no separate scoring path)
- [x] `arip observe` CLI: one-shot, `--window`, `--budget`,
      `--min-recurrence`, `--no-ingest`
- [x] Read-only contract: no source mutation; no PR/alert/replay
- [x] Markdown digest with mandatory "What this digest is NOT" section
- [x] Test coverage: idempotency, cursor resume, mixed
      rule+abstention clusters, quality propagation, source
      immutability
- [x] Stress validation against synthetic noise — see
      [docs/PHASE_A_VALIDATION.md](docs/PHASE_A_VALIDATION.md)
- [x] Real-world ingestion validation (Jaeger / Loki / GHA
      artifact / rotated logs) + operator-side adapters in `bin/` —
      see [docs/INGESTION_GUIDE.md](docs/INGESTION_GUIDE.md)
- [x] Pilot kit + archive skeleton — see
      [docs/OBSERVE_PILOT_KIT.md](docs/OBSERVE_PILOT_KIT.md) and
      [docs/observe-pilot-archive/](docs/observe-pilot-archive/)
- [x] Pilot recruitment + single-command runner + OSS warm-up
      candidates — see
      [docs/observe-pilot-recruitment.md](docs/observe-pilot-recruitment.md),
      [docs/OBSERVE_OPERATOR_BRIEFING.md](docs/OBSERVE_OPERATOR_BRIEFING.md),
      [docs/observe-pilot-candidates.md](docs/observe-pilot-candidates.md),
      `bin/run-observe-pilot.sh`
- [x] **Five runner-self-pilots against unknown OSS systems
      completed** — op001 (HotROD), op002 (CNCF OpenTelemetry
      Demo, healthy), op002b (OTel Demo + fault injection),
      op002c (OTel Demo + fault injection + real Loki logs joined),
      op003 (Grafana Tempo). Two real defects caught + fixed
      (abstention service-set cardinality + Tempo OTLP-JSON
      adapter). NEW operator adapter: `bin/tempo-export-to-bundles.py`.
      **op002c milestone:** first `downstream_error` rule cluster
      fired (high quality band) on an unknown OSS system, validating
      the trust contract end-to-end against real telemetry from
      OTel Demo + Jaeger + Loki.
      See [docs/UNKNOWN_SYSTEMS_VALIDATION.md](docs/UNKNOWN_SYSTEMS_VALIDATION.md).
      **These do NOT count toward Phase 2 entry gate** — explicit
      NO-HUMAN-OPERATOR disclaimers in each archive.
- [x] **Cypress test framework support** — second framework
      alongside Playwright. `arip investigate` auto-detects the
      framework. trace_id extracted from title / err.message /
      extras / W3C traceparent. 16 unit tests
      ([test_cypress_listener.py](arip-core/tests/test_cypress_listener.py)).
- [x] **GitHub Actions observe-mode template** —
      [`.github/workflows/arip-observe.yml.example`](.github/workflows/arip-observe.yml.example).
      Scheduled weekly digest, sticky issue comment, artifact
      upload. Three export options (Jaeger / Tempo / pre-existing
      JSONL artifact) + optional Loki join. Anti-goal-aligned:
      no alerts, no PRs, no auto-remediation.
- [ ] **First REAL engineer pilot** (`op004` or later — real human,
      their own CI/staging telemetry) — operator-coordinated, not
      buildable autonomously. This is the bar for Phase 2 entry gate.

What is **explicitly NOT in Phase A** (will not move without trigger
in [docs/FUTURE_ARCHITECTURE.md item #11](docs/FUTURE_ARCHITECTURE.md)):

- No candidate test generation
- No PR creation
- No sandbox runner
- No alerting or paging surface
- No automatic retention/pruning
- No parallel reasoning system — engine path is unchanged

Trust contract preserved: every observation event passes the existing
evidence audit and abstention gates; observation mode does not bypass
or relax any of them.

## Phase 1.8 — Pilot validation  (active)

Build less. Observe more. The engine is done; the unknown is whether a
real engineer trusts the report. No new rules, no new scenarios, no new
infrastructure — only pilot kit + feedback loop + UX honesty.

- [x] [PILOT.md](PILOT.md) — master pilot kit: what to run, what to
      capture, what success looks like, what is off-limits to change
- [x] [docs/abstention-gallery.md](docs/abstention-gallery.md) — the
      four abstention codes as readable cases with annotations
- [x] [docs/calibration-gallery.md](docs/calibration-gallery.md) — the
      10 calibration benchmark scenarios as readable narratives
- [x] [docs/before-after-investigation.md](docs/before-after-investigation.md)
      — manual vs ARIP-assisted workflow on the same failure
- [x] [docs/pilot-feedback-template.md](docs/pilot-feedback-template.md)
      — short qualitative form for capturing engineer-trust signal
- [x] LLM summariser prompt hedged: "most likely", "evidence suggests",
      "hedge appropriately — input is a hypothesis, not proven fact"
- [x] Pilot execution operationalised:
      [PILOT_RUNBOOK.md](docs/PILOT_RUNBOOK.md),
      [PILOT_METRICS.md](docs/PILOT_METRICS.md),
      [PILOT_SYNTHESIS_TEMPLATE.md](docs/PILOT_SYNTHESIS_TEMPLATE.md),
      [TELEMETRY_PATHOLOGIES.md](docs/TELEMETRY_PATHOLOGIES.md),
      [pilot-archive/](pilot-archive/) skeleton + templates
- [ ] ≥ 3 pilot sessions captured in `pilot-archive/`
- [ ] ≥ 1 synthesis run produced via PILOT_SYNTHESIS_TEMPLATE.md
- [ ] ≥ 1 anonymised real-world telemetry sample integrated into the
      calibration benchmark
- [ ] Friction-point triage: each item routed to next-docs-pass /
      FUTURE_ARCHITECTURE.md / P0 trust-regression

Success criterion: *"a real engineer, in a real CI failure, opens
ARIP's report and says this was actually useful."* Until ≥ 3
independent pilots clear that bar, no new feature ships. Trust is the
moat.

## Phase 1.7 — Real-world hardening  ✓ shipped

The engine declares its own environment's telemetry quality and tells
the operator which rules will not fire under that quality. Designed
around the principle *precision > coverage*: when telemetry is messy,
ARIP abstains more often rather than producing confidently-wrong RCAs.

- [x] Telemetry quality scoring — per-signal coverages + overall score
      + high / medium / low confidence band. Surfaced in every
      investigation report and PR comment.
- [x] Per-rule telemetry contracts as code
      (`arip_core/quality/contracts.py`) — required vs optional
      canonical signals, declared once, surfaced everywhere.
- [x] `arip preflight <report>` — onboarding diagnostic that runs the
      quality assessment + rule-readiness check without writing any
      reports or touching the memory store.
- [x] Calibration benchmark — 10 unit tests codifying expected
      behaviour under messy-telemetry pathologies (missing trace,
      orphan spans, partial retry metadata, HTTP-error without OTel
      ERROR status, sampled retry chain, inconsistent business-key
      naming, …). A high-confidence wrong RCA on any of these is a
      regression.

Trust contract preserved: 4 demo scenarios still produce primary at
0.93–0.95 confidence, stress test still abstains. Quality scoring
never changes rule behaviour — it is purely diagnostic.

## Phase 1.6 — Portability  ✓ shipped

A customer onboards a new environment by writing a config file, not
new rules. Engine + rules are decoupled from raw attribute names via
the canonical-signals layer.

- [x] `NormalizationConfig` dataclass + YAML loader
- [x] `Signals` accessor — every rule reads through it, no rule
      touches `span.attributes[...]` for known signals
- [x] CLI `--config <path>` flag
- [x] `configs/demo.yaml` (default) + `configs/foreign-conventions.yaml`
      (deliberately-different attribute names to prove portability)
- [x] Graceful degradation — every required signal has an explicit
      "what happens when absent" contract documented in
      [docs/ONBOARDING.md](docs/ONBOARDING.md)
- [x] Portability proof: identical rule conclusion under both configs
      via attribute-remapped telemetry replay

## Phase 1.5 — Trust hardening  ✓ shipped

Pre-requisite for any production deployment. Engine must be honest
about uncertainty before it can be trusted to drive decisions at scale.

- [x] Rule template hardening — absolute claims ("every attempt failed",
      "every span above") validated against telemetry before emission
- [x] Assertion-aware adjustment — latency / status / correctness /
      retry tags from the test assertion gently re-rank rules
- [x] Conflicting-hypotheses abstention — engine declines when two
      strong-but-disjoint hypotheses both fire below the trust ceiling
- [x] `flaky_dependency` benchmark — canonical mixed-signal stress test
      that must keep producing abstention as a regression check
- [x] Trust documentation — [docs/CALIBRATION.md](docs/CALIBRATION.md)

Trust metric: *"Would this RCA send an engineer in the wrong
direction?"* Tracked by the canonical scenarios in
[docs/CALIBRATION.md](docs/CALIBRATION.md).

## Phase 2 — Coverage & calibration

Make the engine useful on telemetry it has never seen before.

- [ ] `stale_cache` failure scenario + Redis-aware correlator + rule
- [ ] Statistical anomaly baselines (per-endpoint p50/p99/error-rate)
      so rules stop relying on hard-coded thresholds
- [ ] PR/deploy correlation — link incidents to the commit range likely
      to have caused them
- [ ] Confidence calibration loop — ingest 👍/👎 reactions on PR
      comments as ground truth; tune per-rule priors

Trigger for starting Phase 2: more than one user reports false
positives or false negatives that a baseline would have caught.

## Phase 3 — Production telemetry surface

Lift the engine off the Docker Compose demo and onto real
infrastructure.

- [ ] Kubernetes — swap Docker logs for kubectl events + container logs
- [ ] Service dependency graph (built nightly from spans) — used for
      blast-radius computation
- [ ] eBPF / service-mesh signals — bring L4/L7 failures into scope
      (TCP retransmits, DNS, network policy drops, envoy access logs)

Trigger for starting Phase 3: the engine consistently abstains on
incidents whose root cause is below the OTel application layer.

## Phase 4 — Distributed-systems research

The genuinely-hard, multi-engineer-year work. Off-roadmap until the
earlier phases are deployed.

- [ ] Replayability — deterministic reproduction of failed requests
- [ ] Regression-test generation from investigation reports
- [ ] Causal inference (vs correlation) via OTel `Link`s on async
      boundaries
- [ ] Multi-agent investigation workflows (specialist agents that
      can request more telemetry and refine hypotheses)

Trigger for starting Phase 4: a customer who pays meaningfully more
for time-travel debugging than for a markdown report.

---

## What is explicitly NOT on this roadmap

These are out of scope on purpose, not by accident. Re-evaluate only
if a customer's pain says otherwise:

- Becoming a generic APM / observability vendor
- AI-driven hypothesis generation (LLM-as-engine)
- Auto-remediation / self-healing
- Jira / Slack / PagerDuty integration beyond the GitHub PR surface
- A broad connector ecosystem (one good Jaeger + Docker-logs path is
  worth ten half-baked sources)
