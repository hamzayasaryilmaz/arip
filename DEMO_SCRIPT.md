# Demo / Screencast Script

A reading script for recording a 5–7 minute walkthrough video.
Includes what to say, what to run, what should appear on screen,
what to highlight, and the exact expected output so you can verify
the demo did not drift while recording.

Designed to be skimmable mid-recording: each beat is one fenced
block. Recording markers used throughout:

- **`[PAUSE]`** — beat ends here; let the viewer absorb before continuing
- **`[HIGHLIGHT]`** — call attention to a specific element on screen
- **`[SWITCH → JAEGER]`** — physically switch focus to the Jaeger window
- **`[SWITCH → TERMINAL]`** — physically switch focus back to the terminal
- **`[CLICK]`** — perform a specific UI click
- **`★ DEMO MOMENT ★`** — peak narrative beat, do not rush

## Before recording

```bash
# Clean state: no prior reports, no prior memory, no orphan stack.
cd <repo>
docker compose down -v
rm -rf reports .arip arip-pr-comment.md tests/playwright/playwright-report.json
docker compose up -d --wait
```

Open two terminal windows side by side: **TERMINAL** (left) for
commands and **JAEGER** (right) at <http://localhost:16686>.

Bump font size to ≥ 16 pt. Hide unused tabs.

**Recommended runner:** use `bin/arip-demo-recording.sh` with `--pace slow`
for video. It suppresses tooling noise (uv venv warnings, etc.) and
paces beats so the viewer can keep up. The same beats below map 1-to-1
to the script's output.

---

## Beat 0 · Setup the framing (30 s)

**SAY:**
> "Today I'm going to show you ARIP — Autonomous Reliability
> Investigation Platform. When a Playwright test fails in CI, ARIP
> automatically figures out the root cause from the telemetry you
> already have. It does it deterministically — no LLM in the
> analysis path, no guessing — and it can say 'I don't know' when
> the signal is too weak."

**SHOW:** [README.md](README.md) opened in editor; scroll to the
example output table at the top.

**`[HIGHLIGHT]`** the four high-severity findings in that table.

**`[PAUSE]`** 2 s — let the audience read the table.

---

## Beat 1 · Bring up the stack (45 s)

**SAY:**
> "Everything runs locally on Docker Compose. Six containers — two
> microservices, Postgres, Redis, Jaeger, and an OTel Collector with
> tail-based sampling."

**RUN:**
```bash
docker compose ps
```

**EXPECT:** 6 services Up. Postgres healthy, redis healthy.

**`[HIGHLIGHT]`** point to `arip-otel-collector` and explain its job is
to keep error traces + slow traces no matter what.

**`[PAUSE]`** 2 s.

---

## Beat 2 · Run the demo (90 s)

**SAY:**
> "One command runs the whole investigation pipeline: Playwright
> tests, telemetry correlation, the deterministic engine, fingerprint
> bookkeeping, PR comment rendering."

**RUN:**
```bash
ARIP_DEMO_NONINTERACTIVE=1 bin/arip-demo.sh 2>&1 | tail -120
```

(Or run it interactively for the live "press enter to continue"
feel; non-interactive is better for a tight video.)

**EXPECT:** 4 Playwright failures, 4 ARIP investigations, primary
hypothesis assigned per scenario:

```
webhook_race      → concurrent_modification   (high, conf 0.92)
pool_exhaustion   → db_pool_exhaustion        (high, conf 0.93)
retry_storm       → retry_storm               (high, conf 0.94)  + downstream_error alt
inventory_error   → downstream_error          (high, conf 0.90)
```

**`★ DEMO MOMENT ★`** when the runner prints "Stop D — retry_storm" —
this is the most visually impressive scenario. **`[PAUSE]`** 3 s while
the viewer sees the 5 retry attempt spans with exponential backoff.

---

## Beat 3 · Open one report (60 s)

**SAY:**
> "Let's open the retry-storm investigation. This is what an
> engineer would actually read on the PR."

**RUN:**
```bash
ls reports/ | grep retry
cat reports/checkout-succeeds-without-exhausting-retries-*.md
```

**`[HIGHLIGHT]`** four specific things, in order:

1. **TL;DR**: "Retry storm: 5 attempts to inventory.reserve_attempt
   with exponential backoff. Amplification factor 5×." **`[PAUSE]`** 2 s.
2. **Primary hypothesis** line: severity high, confidence 0.94, rule
   `retry_storm`. **`[HIGHLIGHT]`** confidence number specifically.
3. **Suggested next step**: "Stabilise the downstream first — every
   retry hit the same failure."
4. **Evidence**: scroll through the five `inventory.reserve_attempt`
   spans with `retry.attempt=1..5` and
   `retry.backoff_ms=0/50/100/200/400` verbatim.

**`★ DEMO MOMENT ★`** call out: "Notice how every claim has a
trace_id and span_id cited next to it. The audit layer drops any
ungrounded reference, so this is never bullshit."

**SAY:**
> "Note: nothing here is invented. Every cited span_id and log line
> exists in the live telemetry — the engine audits its own evidence
> before reporting."

---

## Beat 4 · Show the same trace in Jaeger (45 s)

**`[SWITCH → JAEGER]`** open the Jaeger window.

**RUN:** copy the trace_id from the retry-storm report's "Trace:"
line. Paste into Jaeger UI:

```
http://localhost:16686/trace/<that_trace_id>
```

**`[CLICK]`** expand the trace tree to show all 23 spans.

**`[HIGHLIGHT]`** three things, in order:

- The fan-out — one `checkout.process` span containing five
  `inventory.reserve_attempt` children.
- The widening time gaps between attempts (the exponential backoff).
- All five attempts ERROR. All five downstream `inventory.handle_reserve`
  calls ERROR with the same `internal error` message.

**`[PAUSE]`** 3 s — the visual fan-out is one of the strongest moments.

**SAY:**
> "This is the raw signal ARIP read. The report you just saw is a
> faithful summary of these 23 spans — nothing was added, nothing
> was lost."

---

## Beat 5 · Show the PR comment (45 s)

**`[SWITCH → TERMINAL]`** back to the terminal window.

**RUN:**
```bash
cat arip-pr-comment.md | head -40
```

**`[HIGHLIGHT]`** in this order:

- The summary table at the top — one row per failure, severity +
  confidence + flaky verdict + repeat count.
- The collapsed `<details>` blocks below — the engineer scrolls,
  opens what looks interesting.
- Footer note about how this is sticky on the PR via
  `marocchino/sticky-pull-request-comment`.

**`★ DEMO MOMENT ★`** call out: "This is what gets posted on a real
GitHub PR. Re-runs update the comment in place — no thread spam."

**SAY:**
> "This is exactly what gets posted on a GitHub PR. Re-runs update
> the comment in place via the `arip-investigation` header marker —
> the PR thread doesn't get noisy."

---

## Beat 6 · Cross-run fingerprinting (45 s)

**SAY:**
> "ARIP also recognises when a failure has happened before. Each
> hypothesis gets a deterministic fingerprint — same root-cause
> shape, same hash."

**RUN:**
```bash
sqlite3 -header -column .arip/memory.db \
  "SELECT primary_rule_id, fingerprint, COUNT(*) AS occ
     FROM investigations
    WHERE fingerprint IS NOT NULL
    GROUP BY primary_rule_id, fingerprint"
```

**EXPECT:**

```
primary_rule_id          fingerprint       occ
-----------------------  ----------------  ---
concurrent_modification  29cb8520c4f61051  2
db_pool_exhaustion       cacda21ed02e005b  2
downstream_error         2db23e4e389cfa6b  2
retry_storm              193713f185d4ac66  2
```

**`[HIGHLIGHT]`** four distinct fingerprints, two occurrences each (one
per run). The fingerprint is independent of trace_ids, order_ids,
and timestamps.

**`★ DEMO MOMENT ★`** — the fingerprint is the cross-run identity. Same
shape → same hash. Different trace IDs, different orders, same answer.

**SAY:**
> "In real CI this means after the third or fourth time a pattern
> shows up, the PR comment can say 'this same root-cause shape has
> been seen 7 times in the last 14 days — probably worth fixing
> properly.'"

---

## Beat 7 · Show abstention (30 s)

**SAY:**
> "The engine refuses to fabricate findings. When the signal is too
> thin, it tells you so."

**RUN:**
```bash
cat docs/examples/abstention.md | head -30
```

**`[HIGHLIGHT]`** the "Engine abstained" block — the four abstention
codes (no_primary_trace, empty_telemetry, no_rule_matched,
weak_evidence) are documented contracts, not surprises.

**`★ DEMO MOMENT ★`** — call out: "Watch what happens when the engine
DOESN'T know. It doesn't make something up. It says abstain, names the
code, and shows diagnostics. This is the trust property."

**SAY:**
> "This is the property that makes the rest of the output
> trustworthy: when ARIP says something is a retry storm at
> confidence 0.94, it means it. When it doesn't have the signal,
> it says so explicitly."

---

## Beat 8 · The honest scope close (30 s)

**SAY:**
> "Two things this is not. First, it isn't a generic APM — ARIP is
> deliberately narrow, focused on post-failure investigation of
> Playwright tests. Second, it isn't an autonomous-remediation
> system or a deterministic replay platform — those are explicitly
> off the MVP roadmap, with triggers for revisiting documented in
> `docs/FUTURE_ARCHITECTURE.md`."

**SHOW:** [ROADMAP.md](ROADMAP.md) Phase 1 ✓ shipped, Phase 2/3/4
deferred with triggers.

**SAY:**
> "That's the demo. The whole engine is about 800 lines of Python
> across five small modules, 62 unit tests, MIT-style license.
> Repository is at <repo URL>. Thanks for watching."

---

## Total runtime

| Beat | Duration | Cumulative |
|------|----------|------------|
| 0 — framing                    | 30 s | 0:30  |
| 1 — bring up stack             | 45 s | 1:15  |
| 2 — run demo                   | 90 s | 2:45  |
| 3 — open one report            | 60 s | 3:45  |
| 4 — same trace in Jaeger       | 45 s | 4:30  |
| 5 — PR comment                 | 45 s | 5:15  |
| 6 — cross-run fingerprints     | 45 s | 6:00  |
| 7 — abstention                 | 30 s | 6:30  |
| 8 — honest scope close         | 30 s | 7:00  |

About 7 minutes. Cut Beat 7 if you need to land at 6:30.

## If something looks wrong on the day

| Symptom                                       | Quick fix                                              |
|-----------------------------------------------|--------------------------------------------------------|
| `docker compose ps` shows < 6 services Up     | `docker compose down -v && docker compose up -d --wait` |
| Engine abstains on `webhook_race`             | Bump `sleep 8` → `sleep 12` in `bin/arip-e2e.sh`        |
| Reports/ has 8 instead of 4 reports           | You ran the script twice; that's fine, table dedups at the top |
| Jaeger trace link 404s                        | Wait 5–10 s more, then click again (collector flush)    |
| `bin/arip-demo.sh` fatal-errors on preflight  | Install the missing tool from the table at the top      |

Do a dry run end-to-end ≤ 30 minutes before recording.
