# Slide deck prompt — engineering architecture review

Generate a 20-30 slide **engineering architecture review** deck
about ARIP. **Not** a sales deck. **Not** a launch deck. The
closest reference points are:

- A staff engineer's internal architecture review at a tech
  company (the kind that ends with "here are the risks I want
  this room to validate")
- An academic systems-paper accompaniment deck
- A conference talk where the speaker explicitly says "I'm not
  pitching, I'm reporting"

Before generating, read [README.md](README.md) in this directory.
Use its audience-layer rules, "What NOT to say" list, and
"Proven vs hypothesis vs unknown" classifier.

## Deck structure (25 slides ± 5)

| # | Slide | Type | Audience |
|---|---|---|---|
| 1 | Title — "ARIP v0.1.0: deterministic CI investigation, with abstention" — name, date, "engineering architecture review" subtitle | Title | n/a |
| 2 | What this deck is and is not | Statement | senior |
| 3 | The problem in one slide: scattered evidence across one user request | Diagram | beginner-friendly visual |
| 4 | Five concepts the audience needs (log / trace / span / OTel / RCA) — one line each | Definitions | beginner |
| 5 | What ARIP does, in one sentence | Statement | intermediate |
| 6 | The 5-rule table | Table | intermediate |
| 7 | Architecture: collector → correlator → engine → reporter | Diagram | intermediate |
| 8 | The trust contract: 5 abstention codes | Table | intermediate |
| 9 | Why deterministic, not LLM-driven (the LLM's confined role) | Comparison | senior |
| 10 | Evidence audit — every cited span_id must exist in telemetry | Statement | senior |
| 11 | Canonical signals layer (`NormalizationConfig`) — portability via config | Diagram | senior |
| 12 | Observation mode — what it is, what it isn't | Statement | intermediate |
| 13 | Per-source ingestion adapters (Jaeger, Loki, GHA artifact) | Diagram | intermediate |
| 14 | Cluster store + fingerprint stability (the two real fixes from validation) | Technical | senior |
| 15 | **HotROD validation — what happened, honestly** | Story | intermediate → senior |
| 16 | The non-negotiable statement: "zero false-high-confidence outcomes on telemetry the engine had never seen" — with explicit caveat that this is the bound being reached by silence | Headline | intermediate |
| 17 | Telemetry pathologies catalogue (real observed + pre-pilot validation findings) | Table | intermediate |
| 18 | **What is PROVEN** (verbatim from README.md) | Table | senior |
| 19 | **What is HYPOTHESIS** (verbatim from README.md) | Table | senior |
| 20 | **What is UNKNOWN** (verbatim from README.md) | Table | senior |
| 21 | What is intentionally NOT built — anti-goals from POSITIONING.md | List | senior |
| 22 | The no-drift contract enforced in code (import test) | Snippet | senior |
| 23 | Calibration benchmark — 10 scenarios that prevent regression | Test list | senior |
| 24 | Where we are: v0.1.0, post-validation, pre-first-real-engineer-pilot | Status | all |
| 25 | Open risks I want this room to validate (see "Risks to raise" section below) | List | senior |
| 26 | How to engage: try the demo / participate in op002 / read the source | CTA | beginner |
| 27 | Q&A | Section | n/a |

If 25 is the natural cap for your audience's attention, drop
slides 11, 13, 22, 23 — they go in the appendix.

## Slides that MUST be present (cannot be cut)

| Slide # | Why non-negotiable |
|---|---|
| 2 | "What this deck is not" sets the honest tone for the rest |
| 8 | The abstention table is the moat |
| 15 | HotROD is the most honest validation evidence we have |
| 16 | The headline statement, with its caveat, is the single most important sentence |
| 18-20 | Proven / Hypothesis / Unknown — without these, audience can't calibrate trust in the rest |
| 21 | Anti-goals — without these, the audience could leave thinking ARIP is an APM |
| 25 | Open risks — distinguishes architecture review from sales pitch |

## Slide 2 — "What this deck is and is not" content

Required content:

```
What this deck IS

  - An engineering architecture review of ARIP v0.1.0
  - A factual report of what works, what doesn't, what's unproven
  - An invitation to push back on design decisions

What this deck IS NOT

  - A product launch
  - A pitch for investment
  - A claim that ARIP replaces APM / Honeycomb / Datadog
  - A claim that ARIP is "production-ready" (it's v0.1.0)
  - A demonstration of AI capability (no LLM in the analysis path)
```

## Slide 15 — HotROD story content (honest framing)

Required structure:

```
What we did
  - Ran ARIP observe-mode against jaegertracing/example-hotrod
  - Default config, no naming cleanup, no attribute injection
  - 40 trace bundles ingested across 6 services

What happened
  - 0 rule-grounded clusters (no rule's contract matched HotROD's signals)
  - 1 abstention cluster (no_rule_matched × 40)
  - Quality band: 100% medium (no log correlation)

Two real findings + narrow surface fixes
  - handler_operation_patterns default is demo-specific  →  pre-pilot checklist updated
  - self-audit hint block missing 100%-abstention case  →  one bullet added

The honest verdict
  - Trust contract held: zero false-high-confidence outcomes
  - But: the bound was reached by being silent, not insightful
  - HotROD telemetry would need both hygiene improvements
    (HotROD's job) and a config override (known knob) to produce
    actionable clusters
```

This slide is NOT a success-story slide. If you generate it as
"ARIP successfully validated against real-world OSS system",
regenerate it.

## Slide 16 — Headline content

Required content:

```
ZERO false-high-confidence outcomes
on telemetry the engine had never seen.

(This is the single most important validation finding.)

Read it as:
  - The trust contract was given an opportunity to fail loudly
    on unknown input — it didn't.

NOT as:
  - "ARIP solves root-cause analysis."
  - "ARIP works on any system."
  - "ARIP is production-ready."

The bound was reached by being silent, not insightful.
That's the right starting point — but it is a starting point,
not a destination.
```

## Slide 25 — "Open risks to validate" content

Required structure (template; fill with specific risks):

```
Open risks I want this room to push back on:

1. The 5-rule set may be too narrow for non-CI-pattern failures.
   - Validation gate: ≥ 3 independent pilots clear Phase 2 entry

2. Configuration-based portability assumes operators will write
   NormalizationConfig overrides.
   - Validation gate: op002 onboarding ≤ 30 minutes

3. Cross-run fingerprinting assumes engineers will act on
   recurrence signals.
   - Validation gate: pilot reports "I noticed this was recurring"

4. The Phase B/C/D candidate-generation direction may never
   trigger.
   - Validation gate: ≥ 3 pilots verbatim ask for it

5. The trust contract is enforced via abstention discipline +
   calibration tests. A determined contributor could weaken it
   silently in code review.
   - Validation gate: any PR weakening it is rejected; the
     import-test fails loudly if observation-mode drifts
```

## Visual style

- Monospace for code / commands
- Tables, not bullet-soup. The 5 rules are a table. The 5
  abstention codes are a table. The Proven/Hypothesis/Unknown
  matrix is 3 tables.
- One diagram per architecture slide; nothing fancier than
  boxes-and-arrows. Mermaid is fine if exporting via marp /
  reveal.js.
- No screenshots of competing tools. No competitive comparisons.
- The HotROD slide can include a screenshot of the actual digest
  produced (it's in [observe-pilot-archive/op001/digest.md](../observe-pilot-archive/op001/digest.md))
- The "proven/hypothesis/unknown" slides use three columns,
  short text, no logos.

## What NOT to include

In addition to the global "What NOT to say" list in
[README.md](README.md):

- A "competitive landscape" matrix. ARIP isn't competing.
- A "pricing" or "business model" slide. There isn't one yet.
- A roadmap with dates. Roadmap items are trigger-gated, not
  date-gated.
- A "team" slide. The project is currently small; a team slide
  would either overstate or be irrelevant.
- A "logo wall" of customers. There are no customers.
- A "we use Anthropic / OpenAI / etc" slide implying AI
  sophistication. The LLM paraphrases the TL;DR. That's it.
- A "this could be valued at $X" slide. Out of scope.

## Audience layer adaptation

Default deck targets **senior / distributed-systems engineer**
(architecture review audience).

For other audiences, do not generate a different deck — generate
**a subset**:

- **Intermediate engineer version** (15 slides): drop 9-11, 22-23.
  Replace slide 25 with "open questions" framed less formally.
- **Beginner version** (10 slides): drop 9-14, 17, 22-23. Replace
  slide 16's wording with "no false confident answers on a system
  we had never tested".

## Output format

Markdown with one `## Slide N — <title>` heading per slide. Each
slide section contains:

- `### Headline:` the one-line takeaway
- `### Body:` the content (table / list / statement)
- `### Speaker notes:` what the speaker says when this slide is up
- `### What this slide is NOT:` one line — corrects the most
  common misreading

If exporting to actual slide software, marp-compatible front
matter at the top is fine but not required.

## Final sanity pass

Before delivering:

- [ ] All MUST-be-present slides are in
- [ ] Slide 15 frames HotROD honestly (0 useful clusters
      acknowledged, not hidden)
- [ ] Slides 18-20 (Proven / Hypothesis / Unknown) are present
      and verbatim from `README.md`
- [ ] Slide 21 has the full anti-goal list from POSITIONING.md
- [ ] No banned phrase from `README.md` "What NOT to say" appears
      in any slide body or speaker note
- [ ] No competitive comparison anywhere
- [ ] No "production-ready" claim anywhere
- [ ] Closing CTA points at the repo + how to participate in op002
      (op002 not yet run; framing reflects that)
- [ ] Open-risks slide is direct, not hedged

If any of these fail, regenerate the affected slide.
