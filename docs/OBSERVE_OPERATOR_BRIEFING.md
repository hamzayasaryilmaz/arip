# ARIP observe-mode — 5-minute operator briefing

You're about to spend ~30 minutes running ARIP's observe-mode
against a window of your telemetry and telling us honestly what you
see. This is the only doc you need to read first. Five minutes.

## What ARIP observe-mode does

It reads a window of OpenTelemetry trace bundles you give it, runs
five deterministic rules over each trace, and emits a markdown
**digest**: a short list of *recurring* anomaly patterns it has seen,
grouped by what the rules say is the same shape.

The five rules:

| Rule | What it claims |
|---|---|
| `retry_storm` | Many retry attempts of the same operation, same failure reason |
| `db_pool_exhaustion` | Database connection pool saturated, requests waiting |
| `downstream_error` | An ERROR span chain crossing a service boundary |
| `concurrent_modification` | Two traces touched the same business key in overlapping windows with conflicting state transitions |
| `latency_vs_db` | Handler latency dominated by a slow database span |

Nothing else fires. No AI generates new rules on the fly. The set
is what it is.

## What it doesn't do

- Doesn't open PRs
- Doesn't generate tests
- Doesn't send alerts
- Doesn't call out to any external service
- Doesn't replace your APM / dashboard / SIEM / log search
- Doesn't predict the future
- **Doesn't claim to be a root-cause oracle.** Every cluster in the
  digest is "evidence-aligned recurring pattern", never "confirmed
  root cause."

If during the pilot you find yourself thinking "but I wish it
did X" — that's a useful data point. Tell us. Don't expect the
session to deliver it.

## The two cluster types you'll see

**Rule-grounded clusters.** The engine ran a rule and the evidence
supported promoting a primary hypothesis. Each rule-grounded cluster
gets a name (one of the five rules above), a recurrence count
(how many traces shared this shape), and a service list.

**Abstention clusters.** The engine looked at telemetry and
*declined* to nominate a primary hypothesis. There are five reasons
it might decline:

| Abstention code | What it means |
|---|---|
| `no_primary_trace` | The trace_id was promised but the spans never showed up (sampled out, lost in pipeline) |
| `empty_telemetry` | No spans or logs in the time window |
| `no_rule_matched` | The trace looks fine — none of the five rules' contracts triggered |
| `weak_evidence` | A rule almost fired, but the evidence was below the trust threshold (single evidence kind, low confidence) |
| `conflicting_hypotheses` | Two rules wanted to fire with similar confidence on disjoint evidence — engine refused to pick one |

**Abstentions are not failures.** They're how the engine says "I
don't know" instead of guessing. A digest that's mostly abstentions
is honest output, not broken output.

## How to read the digest

Open the markdown. Read top-to-bottom in order:

1. **Run summary.** What was ingested. Quality band distribution.
   This is your calibration — if it says `quality band: low=40,
   medium=10` you're looking at thin telemetry and your trust bar
   should be lower.

2. **Recurring patterns (rule-grounded).** The actually-interesting
   table. Each row is a recurring pattern. Look at the recurrence
   column first; ≥ 5 means "we saw this 5+ times". The services and
   operations columns tell you where to look in your code.

3. **Recurring abstentions.** Each row is a *recurring telemetry
   shape the engine couldn't ground*. Often the most useful section,
   because it points at telemetry-hygiene gaps (e.g. logs without
   trace_id) rather than at code problems.

4. **What this digest is NOT.** A 4-line disclaimer that's always
   there. We deliberately keep it visible — it's part of the trust
   contract.

## What we want you to do during the session

Open the digest. Don't narrate as you read; just read it like you'd
read any other PR description.

Then answer **honestly**:

- Did anything in the digest tell you something you didn't already
  know about your system?
- Was any cluster misleading — i.e. claiming a pattern that isn't
  actually there?
- Which sections did you skip / ignore / find pointless?
- If we offered to run this every Monday morning against last week's
  telemetry, what would you say?

**"This wasn't useful" is a valid and welcome answer.** It's
specifically what we want to hear if it's true. The corpus needs
honest data, not polite answers.

## What we will NOT ask you to do

- Compare to your existing tools at length
- Speculate about what "would be" useful
- Validate a sales narrative
- Sign an NDA
- Provide raw production telemetry (you give us a file you've
  pre-screened; we keep aggregate counts and your verbatim
  feedback)

## A note about confidence numbers

When a rule-grounded cluster shows up, it has a confidence band
internally (high / medium / low), but the digest deliberately
*doesn't* surface a raw 0.0–1.0 number. We found that raw numbers
get over-trusted. The band you'll see is implicit in whether the
engine promoted the cluster as rule-grounded at all (it crossed
the trust threshold) vs. left it in abstention (it didn't).

If you ever see a digest sentence saying "we are 92% certain X is
the cause" — that's a regression. Tell us. The engine's vocabulary
is "evidence suggests", "the recurring pattern is", "most likely",
never "we are certain".

## A note about your telemetry

Real production telemetry is messier than demo telemetry.
Common pathologies you may see surface as abstention clusters:

- Orphan spans (parent dropped by sampling)
- Logs missing `trace_id`
- Path-parameter operation names (`POST /checkout/order-12345`)
- Partial retry attribute metadata

These are not ARIP bugs. They're statements about what your
telemetry contains. ARIP's response to each is documented in
[TELEMETRY_PATHOLOGIES.md](TELEMETRY_PATHOLOGIES.md). Many pilots'
most useful output is a punch list of telemetry hygiene to fix —
*before* the rule clusters become trustworthy.

## What happens after the session

The pilot runner fills three short templates from your verbatim
words and the runner's observations:

- `operator-notes.md` — what the runner saw you do
- `usability-findings.md` — concrete improvements (docs / wording)
- `feedback.md` — your verbatim quotes

You'll see what's about to be committed before it's committed. You
can ask for anything to be scrubbed or paraphrased. Anonymous
attribution is the default; opt-in to initials or full name.

The archive lives at
[docs/observe-pilot-archive/](observe-pilot-archive/) in the repo,
public, alongside the rest. It directly shapes what gets built
next. A single pilot's verbatim line can re-prioritise an entire
quarter of work — yours included.

## Ready?

Pilot runner runs:

```
./bin/run-observe-pilot.sh <your-telemetry-source> op<NNN>
```

You read the digest it produces. The runner sits quietly and watches.
Conversation follows. Templates get filled. Done.

Thanks for spending 30 minutes on this.
