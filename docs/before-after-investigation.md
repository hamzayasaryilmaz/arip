# Before / after — investigation workflow

A side-by-side comparison of how an engineer investigates the *same*
distributed failure with and without ARIP. The failure is real: the
`retry_storm` scenario from the demo stack, captured verbatim from a
live run.

The point is not to claim a specific speed-up — that depends on the
engineer's familiarity with the codebase, their tracing UI, and how
they organise their own thinking. The point is to show what changes
in **shape**: what the engineer reads, in what order, and what they
*don't* have to do anymore.

## The failure

```
Test:     checkout succeeds without exhausting retries (FAILS under retry_storm)
Output:   Error: expected 200 OK; got 502 after retry policy ran
Trace:    <new trace ID per run>
Affected: payment-service ←→ inventory-service
```

## Before — manual debugging

What an engineer would typically do, in approximate order:

```
1.  Open CI run output.
    ↓
    Notice: "expected 200, got 502"
    Time: 30s

2.  Skim test code to remember what the test asserts.
    Time: 1m

3.  Locate the trace_id.
    The test logs it as an annotation, but few engineers know that
    by heart on day one. They usually:
        • search the CI logs for "trace"
        • or scroll through Jaeger's recent traces hoping to find a
          matching timestamp + path
    Time: 1-5m

4.  Open Jaeger.
    Notice the trace fans out into N spans across two services.
    Click around to find which one started erroring.
    Time: 2-5m

5.  Notice multiple "inventory.reserve_attempt" spans.
    Realise this is a retry loop.
    Open each one, observe the retry.attempt attribute.
    Time: 2-5m

6.  Check inventory-service logs to confirm the error.
    Filter by trace_id (if they remember docker has trace_id).
    Time: 2-3m

7.  Form hypothesis: "the downstream is failing consistently and we
    are retrying it 5 times".
    Time: 1m

8.  Decide what to do next: stabilise downstream, look at retry
    budget, adjust backoff?
    Time: 1m

9.  Write a few sentences in the PR describing the finding.
    Time: 3-5m
```

**Total elapsed: ~15-30 minutes**, depending on tooling familiarity.
The investigation is right; the time spent is in *finding the
signal*, not interpreting it.

What the engineer is actually doing for most of those minutes:

- Correlating IDs across systems (CI → trace ID → Jaeger UI → logs)
- Skimming spans to find the interesting ones
- Translating raw attributes into a story

## After — ARIP-assisted

The engineer opens the PR. ARIP has already left a sticky comment.
The flow becomes:

```
1.  Read the table at the top of the comment.
    One row, ≤ 100 characters.
    "Retry storm: 5 attempts to inventory.reserve_attempt — high, 0.94"
    Time: 10s

2.  Expand the <details> block.
    See:
      - One-paragraph description of the dynamic
      - Suggested next step (specific, actionable)
      - Evidence — every attempt span listed with retry.attempt,
        backoff, reason; downstream error explicitly named; ERROR
        logs cited
      - A trace link (clickable, goes straight into Jaeger)
    Time: 30s

3.  Decide:
      - Trust the primary → click trace link to verify the cited
        spans look right → act
      - Distrust the primary → read alternative hypotheses, weigh
        manually, click trace link

    Either way, the engineer never had to:
      - Find the trace_id (it's in the report)
      - Filter logs by trace_id (already done, ERROR logs cited)
      - Identify which spans are interesting (already cited as evidence)
      - Form the retry-loop hypothesis from scratch (already stated)
    Time: 30s-2m

4.  Write a PR response — often "Yep, retry storm. Stabilising
    downstream first as ARIP suggested."
    Time: 1m
```

**Total elapsed: ~3-5 minutes** on the demo stack. The interpretation
work is still the engineer's. The correlation work is gone.

## What is the *same* in both flows

- The engineer still has to understand the failure.
- The engineer still has to decide whether the hypothesis is right.
- The engineer still has to act on the finding.
- The engineer still has to write the PR response themselves.

ARIP does not replace the engineer's judgement. It removes about
80% of the correlation grunt-work that happens *before* judgement.

## What is *different* in both flows

- The engineer reads a sentence, not 30 spans.
- The engineer follows a link, not a search workflow.
- The engineer's mental model is built **from** the evidence, rather
  than **toward** the evidence.
- The engineer's PR response can quote ARIP, rather than re-derive
  the same conclusion in their own words.

## When ARIP does *not* help

Honest list:

- The first time an engineer sees ARIP, they spend an extra 2-3
  minutes learning to read the report layout. There is no shortcut
  to this; it's a one-time cost.
- If the failure pattern is one ARIP's rules don't cover, the report
  abstains with `no_rule_matched`. The engineer is back to manual
  debugging — but with a clean timeline already assembled, not from
  scratch.
- If the failure pattern is ambiguous (the `flaky_dependency` shape),
  ARIP abstains with `conflicting_hypotheses` and surfaces all
  candidates. The engineer has to weigh them by hand. This is still
  faster than starting from raw spans, but it's less of a win than
  the unambiguous case.
- The trace links in the comment go to a Jaeger UI. If the
  engineer's team uses a different trace backend, those links
  resolve to nothing useful. Config can repoint them; this is an
  onboarding step.

## What an engineer thinks after reading

The pilot-feedback template (`docs/pilot-feedback-template.md`)
captures three specific questions worth answering:

- Did you trust the primary hypothesis? (Y / partially / N)
- Would you have arrived at the same conclusion unaided?
- Where did the report mislead you, even slightly?

Capturing those three answers from each pilot is the single most
valuable activity of this phase. ARIP's job after that is to act on
the answers, not to add features.
