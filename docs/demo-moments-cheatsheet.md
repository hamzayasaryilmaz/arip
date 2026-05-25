# Demo moments cheatsheet

The six things in ARIP that make a good demo land. Stick to these
when recording, talking, or screen-sharing.

If a beat is not in this list, **it does not belong in the demo**.
Extra material dilutes the few moments that actually carry the
narrative.

## 1 · Retry chain reconstruction  ★★★

**Where:** the `retry_storm` report; also visible in Jaeger as a
fan-out of 5 sibling spans on one trace.

**What to call out:**

> "One logical user request fanned out to five downstream calls.
> The trace shows that verbatim. ARIP read it, attributed each
> attempt to the retry policy, and surfaced the amplification
> factor on its own."

**Why it lands:** five spans with widening time gaps is a strong
visual. The exponential backoff (0 → 50 → 100 → 200 → 400 ms) is
deterministic, so the screenshot is reproducible.

**Pause:** 3 s after switching to Jaeger.

---

## 2 · Evidence-backed RCA, no LLM  ★★★

**Where:** any report's "Evidence:" section. Best on `retry_storm`
(11 cited evidence items).

**What to call out:**

> "Every line here points at a real span_id or a real log line.
> The audit layer drops anything that doesn't exist in telemetry.
> No marketing language, no synthesised narrative. This is what
> the deterministic engine produced; the LLM is allowed to
> paraphrase but cannot introduce new claims."

**Why it lands:** the contrast with AI hype tools is direct.
Engineers recognise it immediately.

**Pause:** 4 s on the evidence block.

---

## 3 · Abstention as a feature, not a failure  ★★★

**Where:** `docs/examples/abstention.md` or live by running the
`flaky_dependency` benchmark (`docs/CALIBRATION.md`).

**What to call out:**

> "Watch what happens when the engine doesn't know. It doesn't make
> something up. It says abstain, names the code, and shows
> diagnostics. The earlier version of this engine would have
> confidently pointed at the wrong layer here — that's the kind of
> regression the trust contract prevents."

**Why it lands:** most engineers expect "AI tools" to produce
confident output. The willingness to say "I don't know" is the
single biggest differentiator.

**Pause:** 4 s on the "Engine abstained" banner.

---

## 4 · Cross-run fingerprinting  ★★

**Where:** the memory store after a second consecutive run.

```bash
sqlite3 .arip/memory.db \
  "SELECT primary_rule_id, fingerprint, COUNT(*) AS occurrences
     FROM investigations
    WHERE fingerprint IS NOT NULL
    GROUP BY primary_rule_id, fingerprint"
```

**What to call out:**

> "Four distinct fingerprints, two occurrences each. The fingerprint
> is computed from the rule_id, the service set, and the evidence
> shape — independent of trace IDs and timestamps. In production
> this is how ARIP knows 'this same root-cause shape has been seen
> seven times in the last two weeks'."

**Why it lands:** the SQL table is concise and concrete. No hand-
waving about "AI memory" — it's a hash.

**Pause:** 3 s on the table.

---

## 5 · Portability via config swap  ★★

**Where:** the two config files in `arip-core/configs/`.

**What to call out:**

> "Same engine, same rules. Two configs — one for the demo stack,
> one with deliberately-different attribute names. ARIP's portability
> proof test verifies the same trace produces the same conclusion
> under both."

**Diff one rule** in the YAMLs (e.g. `order.id` vs `tenant.id`) to
make the abstraction visible.

**Why it lands:** the OSS audience hears "this is configurable, not
hardcoded to the demo".

**Pause:** 2 s.

---

## 6 · Quality scoring as honest UX  ★

**Where:** the "Environment quality" section in any report, or
`arip preflight` output.

**What to call out:**

> "Every report carries a telemetry quality score. High, medium, or
> low confidence environment. The score never changes rule behaviour
> — but it tells the operator whether the engine was working on
> rich or thin signals. A low-confidence environment means
> 'investigate the abstention diagnostics, not the primary'."

**Why it lands:** demonstrates the engine's calibration discipline
to its own input.

**Pause:** 2 s.

---

## Anti-moments (do not show)

These will dilute the demo. Skip them unless explicitly asked.

- The Python rule source. ARIP looks more impressive at the output
  layer; the source layer can come up if the audience asks.
- Unit tests. Reassuring, but slow on screen.
- The OTel Collector config. Important for credibility, but only
  show if someone questions the sampling.
- The CLI help (`arip --help`). Not visually compelling.
- The Docker Compose file. Same.

## Timing budget

A 7-minute demo, beat by beat:

| Moment                                   | Time   | Cumulative |
|------------------------------------------|--------|------------|
| 0 — framing                              | 30 s   | 0:30       |
| 1 — bring up stack                       | 30 s   | 1:00       |
| 2 — run demo                             | 60 s   | 2:00       |
| 3 — retry chain in Jaeger      ★★★       | 60 s   | 3:00       |
| 4 — open one full report       ★★★       | 60 s   | 4:00       |
| 5 — PR comment                           | 45 s   | 4:45       |
| 6 — cross-run fingerprinting   ★★        | 45 s   | 5:30       |
| 7 — abstention as a feature    ★★★       | 60 s   | 6:30       |
| 8 — close out                            | 30 s   | 7:00       |

Note that moments 1 and 2 are starred ★ but get less screen time —
they require a switch to Jaeger and a SQL query respectively, which
both burn 5–10 s of context switching. Don't try to add a sixth
starred beat.

## What to NOT say

- "AI-powered" — ARIP has zero AI in the analysis path; LLM is
  optional and only for TL;DR.
- "Autonomous" — ARIP reads telemetry, does not act.
- "Self-healing" — explicitly out of scope.
- "Root cause" without "hypothesis" — every primary is a hypothesis,
  not a confirmed cause. Use "primary hypothesis" or "the strongest
  signal".
- "ML model" — there isn't one.
- "Trust the engine" — let the engine earn trust. Show evidence.

## What to ALWAYS say

- "Deterministic" — same input, same output, byte-identical.
- "Evidence-grounded" — every claim cites a real span or log.
- "Honest abstention" — engine can say "I don't know" by design.
- "Portable" — config, not new code, adapts to new environments.
- "Trust-aware" — confidence reflects signal strength, not vibes.
