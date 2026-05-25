# Observe-mode pilot — recruitment package

Copy-paste-ready text for asking an engineer to spend 30 minutes
piloting `arip observe` against their telemetry. One paragraph for
chat / DM, one slightly longer block for email / GitHub issue.

The two versions say the same thing at different lengths. Pick the
one the channel suits. Do not improvise extensions — every addition
weakens the off-limits commitments.

---

## Short version — Slack / Discord / DM

```
Quick ask: would you be willing to run a 30-minute pilot of an open
deterministic CI investigation tool (ARIP) against a window of your
CI/staging OpenTelemetry traces? We're validating the observation
mode against real telemetry. You'd run one command, read a small
markdown digest, and tell us honestly whether it surfaced anything
useful.

What we WON'T do:
 - generate any code or test for you
 - open any PR
 - send anything to a third-party service
 - keep your raw telemetry — only an anonymised quality summary
 - ask you to integrate anything into your stack

What we'd need:
 - 30 min of your time (5 min setup + observe + 25 min reading + chat)
 - One Jaeger / Tempo / Loki / GHA-artifact export from 1 hour of
   activity (you give us the file; nothing is pulled remotely)
 - A 5-min read of the operator briefing first

If interested, reply with a 👍 and I'll send the operator briefing
+ one command to try locally.
```

---

## Long version — email / GitHub issue

```
Subject: 30-min pilot ask: ARIP observe-mode against your CI telemetry

Hi <name>,

I'm validating the first real-world pilot of ARIP's observation
mode and would value your perspective for ~30 minutes.

WHAT ARIP OBSERVE-MODE IS
A deterministic CI investigation engine that reads OpenTelemetry
trace bundles and emits a markdown digest of recurring anomaly
patterns. No AI generates the analysis — five fixed rules
(retry_storm, db_pool_exhaustion, downstream_error,
concurrent_modification, latency_vs_db) decide what counts as an
anomaly; everything else lands in an honest abstention.

It is NOT:
 - an APM or dashboard
 - an alerting tool (no notifications go anywhere)
 - a candidate test generator (deferred capability, gated)
 - an autonomous agent (no AI-driven decisions)
 - an observability platform

WHAT WE'D ASK YOU TO DO

  Total time: ~30 minutes
  ----------------------------------------------------------------
   5 min  Read OBSERVE_OPERATOR_BRIEFING.md
   5 min  Export 1 hour of CI/staging telemetry from your stack
          (Jaeger, Tempo, Loki, GHA artifact zip — your choice)
   2 min  Run one shell command:
            ./bin/run-observe-pilot.sh <your-export> op001
   5 min  Read the markdown digest the command produces
  10 min  Conversation: what did you see, what was useful, what
          was confusing, what would you ignore
   3 min  We fill in templates from your verbatim responses (no
          interpretation), commit the archive to a public
          calibration corpus

WHAT WE WON'T DO

 - Generate code, tests, or PRs
 - Send your telemetry to any external service (ARIP runs locally)
 - Keep raw trace_ids, customer IDs, internal hostnames — only
   aggregate counts and operation-name shapes go into the archive
 - Ask follow-up "what if you also did X" feature requests
 - Use your feedback for marketing or testimonials

WHAT YOU'D GET BACK

 - The markdown digest (which you can keep or discard)
 - An honest assessment of whether your telemetry hygiene is in a
   state where observation-mode is useful (often the first finding
   is "fix log_trace_correlation" — that's valuable on its own)
 - Your verbatim quotes in the public archive, attributed only with
   your initials and role (or anonymous if you prefer)
 - A small line in the project's calibration corpus, which directly
   shapes what gets built next

PRIVACY

We commit to the archive only:
 - operation-name shapes (with path parameters preserved as
   `/checkout/<order_id>` style if you want them scrubbed; verbatim
   otherwise)
 - aggregate counts (recurrence, quality bands, abstention codes)
 - YOUR verbatim words, edited only for confidentiality if you ask
 - the markdown digest, with anything you flag scrubbed

We will NOT commit:
 - raw trace_ids
 - customer / order / account IDs in raw form
 - log line bodies that may contain PII
 - your name or company unless you explicitly opt in

You can ask for any commit to be amended or removed at any time.

THE TRUST CONTRACT

If the digest contains anything you judge to be confidently wrong —
a rule cluster claiming a pattern that isn't real — we treat that
as a P0 release-blocker and pause future pilots until it's fixed.
That's exactly the kind of feedback we need.

If interested, reply with availability and I'll send the operator
briefing + the one-command pilot runner. Total commitment is
~30 minutes and ends when the conversation does.

Thanks for considering it.

— <your name>
```

---

## Suitability checklist (before sending)

Before sending the package, sanity-check the recipient against:

| Trait | Why it matters |
|---|---|
| Has access to ≥ 1 hour of OpenTelemetry traces they can export | If they can't get the file, the pilot can't start |
| Sees CI/staging failures often enough to have intuition about recurring patterns | Their "is this useful?" answer is calibrated |
| Has 30 uninterrupted minutes — not 30 minutes spread across a day | Body-language and first-action signals need contiguous time |
| Is willing to give verbatim feedback (not sanitised "this is great!" answers) | The corpus needs honest data |
| Is NOT a senior decision-maker the pilot might pressure to "say nice things" | Pilot is for honest signal, not buy-in |

If the recipient fails 2+ of these, the pilot will produce thin
data. Pick someone else or address the gap first.

## What NOT to send alongside

- A demo video
- A pitch deck
- A "how ARIP works under the hood" tech-deep-dive
- Comparisons to other tools
- The ROADMAP.md

The package above is the maximum surface. Anything else dilutes the
ask and turns a 30-min pilot into a 2-hour sales meeting.
