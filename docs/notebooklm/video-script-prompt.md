# Video script prompt — engineering deep-dive

Generate a script for a 15-25 minute YouTube-style **engineering
deep-dive** video about ARIP. **Not** a product launch trailer.
**Not** a marketing piece. The closest reference points are:

- Honeycomb "talks" on observability hygiene
- ThoughtWorks Technology Radar deep-dives
- The "Why I built X" Hacker News-driven engineering talks where
  the speaker spends 5 minutes on what didn't work

Before generating anything, read [README.md](README.md) in this
directory. Use its audience-layer rules, the "What NOT to say"
list, and the "Proven vs hypothesis vs unknown" classifier.

## Script structure (target: 18 minutes ± 3)

| # | Beat | Duration | Audience layer |
|---|---|---|---|
| 0 | Cold open: the problem ARIP exists for (one specific CI failure) | 60s | beginner |
| 1 | Why this is hard: telemetry scatter + scattered evidence | 90s | beginner → intermediate |
| 2 | Why AI-driven RCA tools hallucinate (without naming any) | 90s | intermediate |
| 3 | What ARIP does, in one sentence, then five rules | 120s | intermediate |
| 4 | The trust contract: 5 abstention codes; why "I don't know" is a feature | 150s | intermediate → senior |
| 5 | Live demo: `bin/arip-demo.sh` on the demo stack; show one full report; show a Jaeger link working | 180s | beginner-friendly visuals; intermediate narration |
| 6 | Observation mode: what it does, what it deliberately doesn't | 120s | intermediate |
| 7 | The HotROD validation: what happened when the engine met a system it had never seen | 180s | intermediate → senior |
| 8 | What's proven vs what's hypothesis vs what's unknown (explicit slide on screen) | 120s | all three |
| 9 | What's deliberately NOT built (anti-goals from POSITIONING.md) | 90s | senior |
| 10 | Where the project is now: v0.1.0, post-validation, pre-first-real-engineer-pilot | 60s | all three |
| 11 | Closing: how to try it; where to read more | 60s | beginner |

Total: ~21 minutes including pauses.

## Audience layer for the whole video

**Default to intermediate engineer.** Beats 0-1 and 5 (demo) drop
to beginner. Beats 4, 7, 9 lift to senior. Never blend in one beat.

If the user wants a beginner-only or senior-only version, generate
a separate script — do not try to serve all three in one take.

## Tone calibration per beat

| Beat | Tone |
|---|---|
| 0 (cold open) | First-person, specific, no jargon. "Last week a colleague spent two hours on a flaky checkout test before realising the database pool was saturated. The evidence was in the trace the whole time." |
| 4 (trust contract) | Tight, definitional, slightly emphatic. "If I'm going to be wrong, I refuse to answer." |
| 7 (HotROD) | Honest, including the things that did not work. "The engine produced zero useful rule clusters. That sounds bad. It's actually exactly what should have happened." |
| 9 (anti-goals) | Direct, structural. Read from POSITIONING.md anti-goal list verbatim. |
| 10 (status) | Calibrated, no hype. "v0.1.0. Synthetic noise pass: green. Real OSS validation: one finding, one fix. Real engineer pilot: not yet run." |

## What to show on screen

| Beat | Visual |
|---|---|
| 0 | A real Jaeger trace screenshot (Jaeger HotROD demo is fine) — engineer scrolling, confused face |
| 1 | A diagram: one user click → 5 services → scattered logs/spans/metrics |
| 2 | A table comparing "deterministic verdict" vs "LLM verdict" on the same trace; mark which one hallucinates without naming a vendor |
| 3 | The 5-rule table from [EXPLAINER_BEGINNER.md](../EXPLAINER_BEGINNER.md) "What ARIP actually does" |
| 4 | The 5-abstention-code table; highlight the one that fires most often (`weak_evidence`) |
| 5 | Terminal recording: `bin/arip-demo.sh` end-to-end (~30s); pause on the markdown report; click into Jaeger; show the cited span_id IS the failing span |
| 6 | The "Run summary" + "Recurring patterns" + "Recurring abstentions" sections of an observe digest, side by side with the "What this digest is NOT" disclaimer |
| 7 | The HOTROD_FINDINGS.md headline section; then the per-rule "HotROD fit" table |
| 8 | A 3-column slide: Proven / Hypothesis / Unknown — verbatim from [README.md](README.md) "Proven vs hypothesis vs unknown" section |
| 9 | The POSITIONING.md anti-goal list as a slide |
| 10 | The 4-commit git log (`6faaf50` → `81e0443`); the GitHub Actions success badge |
| 11 | The repo URL, one command (`bin/arip-demo.sh`), the QUICKSTART link |

## What NOT to show

- A flashy intro animation with the ARIP logo dropping. There is no logo.
- A "compared to Datadog/Honeycomb" slide. They're not competitors.
- A "future roadmap" slide promising AI-driven anything. The
  deferred capabilities are trigger-gated — show them but flag the
  triggers, don't promise the destination.
- An "AI did this" framing on the LLM TL;DR step. The TL;DR is a
  paraphrase, not analysis.
- Fictional engineer testimonials. The op001 archive carries an
  explicit NO HUMAN OPERATOR disclaimer; do not pretend otherwise.

## Required "honest moments"

These are non-skippable. Each one must appear verbatim, in tone, at
the indicated beat:

1. **Beat 4:** "The trade-off is honest: sometimes you get 'I don't
   know' instead of 'I have a guess'. In exchange, when ARIP does
   produce a primary cause, you can act on it."
2. **Beat 7:** "The engine produced zero useful rule clusters on
   HotROD. The bound was reached by being silent, not insightful.
   That's still the right outcome — but don't mistake it for
   success."
3. **Beat 8:** "Here's what's proven, what's still hypothesis, and
   what's genuinely unknown."  *(then read the three columns)*
4. **Beat 10:** "No real engineer has used this on their own
   telemetry yet. We're ready for that pilot. Until it happens,
   everything else is preparation."

If the script ever blurs any of these into "ARIP successfully
analysed real-world systems", that's the hype lapse to reject.

## Adaptation per audience layer (if generating multiple versions)

### Beginner-only version (12-15 min)

- Cut Beat 4 from 150s to 90s; keep the trade-off statement.
- Cut Beat 9 entirely; replace with "anti-goals" sentence in Beat 6.
- Lengthen Beat 0 to 90s; spend more time on what telemetry IS.
- Visuals stay; narration uses no acronyms without defining them once.

### Senior-only version (18-22 min)

- Skip Beat 0 entirely (assume the problem statement).
- Lengthen Beat 4 to 4 min; cover the conflict-detection delta
  threshold (`CONFLICT_DELTA = 0.10`) and why
  `CONFLICT_TOP_CONFIDENCE_CEILING = 0.85` exists.
- Lengthen Beat 7 to 5 min; cover the fingerprint multiplicity
  fix (PHASE_A_VALIDATION Appendix A) and the
  abstention-fingerprint operation-name cardinality fix
  (Appendix B) — both real defects caught and fixed during
  validation.
- Add a Beat 7.5: the no-drift import-test contract
  (`test_observation_module_does_not_import_side_effect_surfaces`).

## Hard length cap

If the script exceeds 25 minutes at delivery pace, the script is
too long. Cut Beat 9 first (it can live in the description), then
Beat 6.

## Output format

Markdown, with:

- Beat numbers as `## Beat N — <title>` headings
- `**SAY:**` for narration
- `**SHOW:**` for what's on screen
- `**[PAUSE]**` markers between beats
- An explicit `**[ABSTENTION-PHRASE CHECK]**` marker at the end of
  Beat 4 and Beat 7 — reminds the editor those moments must not
  be cut
- One `**[HONEST CHECK]**` marker after Beat 8 — the
  proven/hypothesis/unknown columns must be read in full, not
  summarised

Reference [DEMO_SCRIPT.md](../../DEMO_SCRIPT.md) for the
investigation-mode beat-style conventions ARIP already uses
internally — match that style.

## Final sanity pass before delivering the script

Before returning the script, run it past these checks:

- [ ] No banned phrase from `README.md` "What NOT to say" appears
- [ ] All claims tagged Proven / Hypothesis / Unknown OR clearly
      attributable to a repo source
- [ ] HotROD beat honestly states "zero useful rule clusters",
      not "successful real-world validation"
- [ ] LLM's role limited to TL;DR paraphrase, never analysis
- [ ] Anti-goals from POSITIONING.md preserved at Beat 9 (or 6
      for beginner-only version)
- [ ] Closing CTA points at repo + QUICKSTART, not at a contact
      form or "request a demo" page

If any of these fail, regenerate the affected beat.
