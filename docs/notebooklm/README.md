# NotebookLM ingestion + content-generation kit

This directory is for an LLM-driven content tool (NotebookLM,
Claude, ChatGPT, Gemini) tasked with **explaining ARIP at multiple
audience levels without producing hype**.

It contains three format-specific prompts plus this cross-cutting
reference. Whatever format you generate (video script, podcast,
slide deck), the rules in this README apply to all of them.

## How to use this kit

1. Load the entire repository as the knowledge corpus for the
   tool. The repo is small (~1500 commits-worth of docs at v0.1.0
   — actually 4 commits, but the docs are exhaustive).
2. **First**, ingest these grounding files in this order — they
   are the trust spine of every output:
   1. [docs/POSITIONING.md](../POSITIONING.md) — the strategy /
      what gets refused
   2. [docs/EXPLAINER_BEGINNER.md](../EXPLAINER_BEGINNER.md) —
      plain-English explanation
   3. [README.md](../../README.md) — top-level capabilities + scope
   4. [docs/OBSERVE_MODE.md](../OBSERVE_MODE.md) — observation
      mode technical reference
   5. [docs/HOTROD_FINDINGS.md](../HOTROD_FINDINGS.md) — the
      single most important honest-tone validation example
3. Pick the format prompt (`video-script-prompt.md`,
   `podcast-prompt.md`, `slide-deck-prompt.md`) and follow it.
4. Cross-check the output against the [*"What NOT to say"*](#what-not-to-say) list
   and the [*"Proven vs hypothesis vs unknown"*](#proven-vs-hypothesis-vs-unknown)
   classifier before publishing.

## Audience layers (apply to every format)

Three target audiences. Pick the layer per format; do not blend
them in one piece.

| Layer | Who they are | What they need to hear | What you can assume |
|---|---|---|---|
| **Beginner** | Curious non-expert; junior dev; technical co-founder; product manager who reads code | Why the problem is hard; what telemetry is; why hallucination matters | Nothing. Define every term the first time. |
| **Intermediate engineer** | Backend developer; SRE familiar with one observability stack; tech lead | What the five rules do; how abstention works; how the engine path differs from AI-driven RCA tools | They know what a span is. They have used Jaeger or similar. |
| **Senior / distributed-systems engineer** | Observability engineer; CTO of a small platform team; distributed-systems veteran | The trust contract enforcement (positioning gates, evidence audit, calibration benchmark); the no-drift contract at the import-test level; why the fingerprint had to drop multiplicity; what's frozen vs trigger-gated | They know vector clocks, causal-vs-correlation distinctions, OTel semantic conventions. |

Adaptation rules:
- A **beginner** version says *"a span is a piece of work inside a
  request"*. A **senior** version says *"the engine reads through
  the canonical-signals layer so attribute names are remapped
  per-deployment via NormalizationConfig"*.
- The **same headline finding** ("zero false-high-confidence
  outcomes on telemetry the engine had never seen") fits all three
  layers — only the supporting detail changes.
- Never **dumb down to the point of imprecision**. *"Deterministic"*
  is fine for all three layers; explain it once for beginners.

## What NOT to say

A hard list. These phrasings push the output into hype, and every
one of them violates the project's actual scope.

### Banned phrases (output rejected if any appear)

- "AI magic" / "AI-powered" / "AI-driven analysis"
- "Autonomous debugging" / "self-debugging" / "self-healing"
- "AIOps" / "AIOps platform" / "next-generation observability"
- "Observability revolution" / "the future of monitoring"
- "Eliminates root-cause analysis" / "replaces engineers"
- "Confidently identifies" / "always finds" / "never wrong"
- "Production-ready" (the project is v0.1.0; pre-pilot)
- "Enterprise-grade" (no enterprise features by design)
- "Industry-leading" / "state-of-the-art"
- "Scales to millions of traces" (unmeasured, see Unknowns)
- "Reduces MTTR by X%" / any percentage benefit not measured in
  the project's own docs
- "Detects anomalies you didn't know existed" (the engine reports
  evidence-aligned recurring patterns, not unknown unknowns)
- "Self-improving" / "learns over time" (the engine is fixed;
  rules don't learn)

### Banned framings

- ARIP as a competitor to Datadog / Honeycomb / New Relic — it
  isn't, and the [POSITIONING.md](../POSITIONING.md) anti-goal
  list says so explicitly
- ARIP as an autonomous agent (Phase B/C/D capabilities are
  trigger-gated; none exist in v0.1.0)
- ARIP as a turnkey solution (it requires per-environment config
  via `NormalizationConfig` for non-demo telemetry)
- "Just install and it works" (the [HotROD findings](../HOTROD_FINDINGS.md)
  document a real onboarding friction; ignore that and you've
  reproduced the hype problem the project exists to refuse)

### Tone calibration

- An honest engineering talk would say *"on the system we tried,
  the engine abstained on every trace because the operation-name
  pattern didn't match the default. We documented that as a
  pre-pilot checklist item."*
- A hype talk would say *"ARIP successfully analysed a real-world
  microservices system."*
- Always pick the first.

## Proven vs hypothesis vs unknown

Every output must explicitly mark these three categories. If a
claim doesn't carry one of these labels, the listener can't tell
where the trust line is.

### Proven (v0.1.0, evidenced in the repo)

| Claim | Evidence |
|---|---|
| Deterministic engine produces reproducible reports across runs | The demo's 4 failures produce stable fingerprints across runs (memory table) |
| 5 rules cover 5 specific failure shapes end-to-end | Unit tests in `arip-core/tests/test_engine_rules.py` and per-rule files |
| Trust contract holds under synthetic noisy telemetry | [PHASE_A_VALIDATION.md](../PHASE_A_VALIDATION.md) Appendix A — 15 stress tests, all pass |
| Observation mode handles real OpenTelemetry export shapes | Same doc Appendix B — 9 ingestion validation tests |
| Zero false-high-confidence outcomes on a never-before-seen OSS system | [HOTROD_FINDINGS.md](../HOTROD_FINDINGS.md) — 40 traces, 0 fabricated rule clusters |
| Calibration benchmark catches confident-wrong regressions | `arip-core/tests/test_calibration_benchmark.py` — 10 scenarios, all pass |
| No-drift contract is enforced in code, not just docs | `tests/test_observation_stress.py::test_observation_module_does_not_import_side_effect_surfaces` |
| Public clone runs 145/145 tests against fresh install | Verified during v0.1.0 push |
| GitHub Actions workflow runs end-to-end on hosted CI | Workflow run for commit `ad30003` completed `success` |
| Apache-2.0 licensed; OSS | LICENSE + GitHub auto-detect |

### Hypothesis (the project assumes these but hasn't validated them)

| Claim | What would change its status |
|---|---|
| A real human engineer finds the digest useful enough to use again | First real-engineer pilot (`op002`) completing with verbatim "yes" |
| Five rules are enough to cover the most common CI failure shapes | ≥ 3 independent pilots clearing Phase 2 entry gate |
| Cross-run memory (fingerprinting) changes engineer behavior | Pilot reporting "I noticed this is recurring and acted differently" |
| Configuration-based portability is operator-tractable | Pilot completing onboarding ≤ 30 minutes (target) |
| The QA/regression-assistance Phase B/C/D direction is worth pursuing | Pilot post-mortems stating it would meaningfully accelerate their work |

### Unknown (not measured; honest gaps)

| Question | Why unmeasured |
|---|---|
| How does the engine behave on event-sourced / async-messaging architectures? | All validation is request-response shaped |
| How does it scale to > 10,000 traces per pilot run? | Not benchmarked; bounded by per-run `--budget` |
| What's the false-high-confidence rate across many pilots? | Target threshold (< 5%) defined in PILOT_METRICS.md; not yet measured because zero real pilots have completed |
| How well does it handle multi-tenant SaaS telemetry? | No instance has been tried |
| What happens when an engineer disagrees with an abstention? | No engineer has done so yet |

## Practical usage (every format must reference this)

The three real commands a curious engineer would actually run.
Pasting any of these into a generated piece is fine; the commands
are stable.

```bash
# A. Try the demo (30 seconds)
git clone https://github.com/hamzayasaryilmaz/arip.git
cd arip && bin/arip-demo.sh

# B. Check your own telemetry is ingest-able (30 seconds, throwaway)
bin/observe-self-audit.sh /path/to/your/telemetry.jsonl

# C. Run a real pilot session (~30 minutes incl. conversation)
bin/run-observe-pilot.sh /path/to/telemetry.jsonl op002
```

Source files that document these flows in depth (ground every
"how do I run X" claim against one of these):

- [QUICKSTART.md](../../QUICKSTART.md) — Workflow A in 15 minutes
- [DEMO_SCRIPT.md](../../DEMO_SCRIPT.md) — Workflow A as a
  recordable screencast (beats, expected output)
- [docs/OBSERVE_MODE.md](../OBSERVE_MODE.md) — observation mode
  technical contract
- [docs/OBSERVE_PILOT_KIT.md](../OBSERVE_PILOT_KIT.md) — Workflow
  C operator guide
- [docs/INGESTION_GUIDE.md](../INGESTION_GUIDE.md) — per-source
  recipes (Jaeger, Loki, GHA artifact, S3)
- [docs/ONBOARDING.md](../ONBOARDING.md) — what telemetry is
  needed, how to map non-demo conventions
- [bin/run-observe-pilot.sh](../../bin/run-observe-pilot.sh) — the
  pilot wrapper itself
- [bin/observe-self-audit.sh](../../bin/observe-self-audit.sh) —
  the 30-sec smoke check

## Source-of-truth files per topic

When the format prompt asks the LLM to discuss a topic, the LLM
should ground the discussion in the file(s) below. If a topic
isn't listed, the LLM should ask the user before generating.

| Topic | Ground in |
|---|---|
| What ARIP is | [README.md](../../README.md), [EXPLAINER_BEGINNER.md](../EXPLAINER_BEGINNER.md) |
| Why deterministic, not LLM-driven | [POSITIONING.md](../POSITIONING.md), [CALIBRATION.md](../CALIBRATION.md) |
| Five rules + their contracts | [INVESTIGATION_RULES.md](../INVESTIGATION_RULES.md), `arip_core/engine/rules/` |
| Abstention philosophy + 5 codes | [CALIBRATION.md](../CALIBRATION.md), [abstention-gallery.md](../abstention-gallery.md), [EXPLAINER_BEGINNER.md](../EXPLAINER_BEGINNER.md) |
| Observation mode | [OBSERVE_MODE.md](../OBSERVE_MODE.md), [observe-digest-examples.md](../observe-digest-examples.md) |
| HotROD validation | [HOTROD_FINDINGS.md](../HOTROD_FINDINGS.md), [UNKNOWN_SYSTEM_VALIDATION.md](../UNKNOWN_SYSTEM_VALIDATION.md) |
| Architecture + module boundaries | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Trust contract enforcement | [CALIBRATION.md](../CALIBRATION.md), `test_calibration_benchmark.py`, `test_observation_stress.py` |
| Real-world telemetry pathologies | [TELEMETRY_PATHOLOGIES.md](../TELEMETRY_PATHOLOGIES.md) |
| What's deferred and why | [FUTURE_ARCHITECTURE.md](../FUTURE_ARCHITECTURE.md), [ROADMAP.md](../../ROADMAP.md) |
| Pilot process | [PILOT.md](../../PILOT.md), [OBSERVE_PILOT_KIT.md](../OBSERVE_PILOT_KIT.md), [PILOT_RUNBOOK.md](../PILOT_RUNBOOK.md) |
| Per-source telemetry ingestion | [INGESTION_GUIDE.md](../INGESTION_GUIDE.md) |
| Onboarding a new environment | [ONBOARDING.md](../ONBOARDING.md) |

## Format prompts

- [video-script-prompt.md](video-script-prompt.md) — YouTube-style
  engineering deep-dive video, 15-25 min
- [podcast-prompt.md](podcast-prompt.md) — two-person honest
  engineering podcast, 30-45 min
- [slide-deck-prompt.md](slide-deck-prompt.md) — engineering
  architecture review deck, 20-30 slides

Each prompt assumes you have already read this README.

## A note on the project's name

ARIP = *Autonomous Reliability Investigation Platform*. The
*"Autonomous"* in the name is **legacy from an earlier framing**
and is honest about being a noun, not a behavior — ARIP is not
autonomous in operation. The platform investigates without you
having to coordinate the investigation manually; it does not act
on your behalf, deploy fixes, file issues, page anyone, or run
unattended. If you must mention the name's origin, mention this
caveat too.
