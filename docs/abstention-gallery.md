# Abstention gallery

When ARIP says "I don't know", what does that look like to an
engineer, and why is each case the correct behaviour? This page
walks through every abstention code with a concrete example and the
trust reasoning behind it.

If a pilot reader is unconvinced that abstention is useful, point
them here.

## Abstention codes

| Code                          | When it fires                                                          |
|-------------------------------|------------------------------------------------------------------------|
| `no_primary_trace`            | The trace ID from the failing test never appeared in Jaeger            |
| `empty_telemetry`             | No spans or logs available for the failure window                      |
| `no_rule_matched`             | The telemetry shape did not match any deterministic rule's signature   |
| `weak_evidence`               | The best-matching hypothesis was too thin to be primary                |
| `conflicting_hypotheses`      | Multiple rules fired below the trust ceiling on disjoint evidence      |

## Case 1 · `no_primary_trace` — the trace got lost

**Scenario:** Investigation ran ~3 seconds after Playwright fired the
test. The OTel Collector's tail-sampling decision window is 5 seconds
on top of the SDK's own batch interval; the failing trace simply
hadn't reached Jaeger yet.

**What an engineer sees:**

```markdown
## ⚠️  Engine abstained

**Primary trace not found in the telemetry backend.**

The failure carries a trace_id but no spans for that trace were
retrievable from Jaeger after a bounded retry. The trace may have
been sampled out, lost in the pipeline, or not yet flushed by the
SDK. Without the primary trace, any hypothesis would be speculative.

Diagnostics:
- `expected_trace_id` = `00000000000000000000000000000000`
- `related_trace_ids` = `[]`
- `spans_seen` = `0`
```

**Why this is right:** Without the trace, every hypothesis would be
made up. An engine that produces hypotheses from empty input is the
worst possible kind of investigator — overconfident on no signal.

**What the engineer should do:** Check the OTel pipeline health.
ARIP's diagnostics tell them exactly what's missing.

The full rendered example lives at [examples/abstention.md](examples/abstention.md).

---

## Case 2 · `weak_evidence` — best finding too thin

**Scenario:** The engine considered all rules. The top hypothesis had
confidence 0.60 with only one kind of evidence (a single ERROR span).
Below the 0.70 confidence floor and below the 2-evidence-kinds
requirement.

**What an engineer sees:**

```markdown
## ⚠️  Engine abstained

**Top hypothesis lacks corroborating evidence.**

The best-matching rule produced a hypothesis `Latency above the
database layer in inventory-service` with confidence 0.85 and 1
kind(s) of evidence. ARIP abstains from promoting weak hypotheses
to primary status; the finding is listed as a candidate only.

Diagnostics:
- `candidate_confidence` = `0.85`
- `candidate_title` = `Latency above the database layer in inventory-service`
- `evidence_kinds` = `['span']`
```

**Why this is right:** A single-evidence-kind hypothesis is a
single-signal claim. One signal in distributed telemetry is rarely
enough to bet on. The engine doesn't suppress the finding — it
surfaces it as a *candidate*, not the primary.

**What the engineer should do:** Read the candidate. If it matches
their intuition, treat as a strong hint and investigate the cited
span manually.

---

## Case 3 · `no_rule_matched` — a pattern the engine doesn't know

**Scenario:** Test failed; trace exists; no `retry.*` attrs, no
pool stats, no cross-service ERROR chain, no overlapping traces. A
plain ERROR somewhere mid-trace that no shipped rule has a signature
for.

**What an engineer sees:**

```markdown
## ⚠️  Engine abstained

**No deterministic rule matched this telemetry shape.**

The investigation engine has rules covering known failure patterns
(concurrent modification, downstream error, application-layer
latency). None matched. This may be a novel pattern; consider
adding a rule, or escalate to a human.

Diagnostics:
- spans: 14
- logs: 6
- db_queries: 1
```

**Why this is right:** The MVP's rule library is narrow on purpose.
"No rule matched" is honest. If 50% of pilot failures abstain with
this code, that's a strong signal we need a new rule — *driven by
real data, not by speculation.*

**What the engineer should do:** Read the timeline. The report still
includes spans + logs sorted chronologically — manual inspection is
faster than from-scratch CI debugging because trace correlation is
done.

---

## Case 4 · `conflicting_hypotheses` — the engine's hardest case

**Scenario:** The `flaky_dependency` benchmark (see
[CALIBRATION.md](CALIBRATION.md)): inventory's first call returns 503,
payment retries, the retry succeeds but is slow (250 ms artificial
delay). Three rules fire:

- `retry_storm` says "retries happened, downstream is transient"
- `downstream_error` says "downstream returned 503"
- `latency_vs_db` says "the handler latency is the actual problem"

All three are technically reading the trace correctly. None is alone
sufficient to explain the test's SLA failure.

**What an engineer sees:**

```markdown
## ⚠️  Engine abstained

**Multiple plausible but conflicting explanations.**

Two or more rules fired with similar confidence on disjoint evidence.
`retry_storm` (conf 0.79) and `downstream_error` (conf 0.72) cite
different parts of the trace (20% evidence overlap). Each is a real
signal; ARIP declines to promote one as primary because a wrong
choice would send an engineer in the wrong direction. All candidate
findings are listed below — weigh them by hand.

## Candidate findings

### Retry storm: 2 attempts to `inventory.reserve_attempt`
(confidence 0.79)
…

### Downstream inventory-service failure observed (recovered upstream)
(confidence 0.72)
…

### Latency above the database layer in inventory-service
(confidence 0.88)  ← actually closest to the SLA-violation root cause
…
```

**Why this is right:** The earlier version of ARIP confidently picked
`downstream_error` at 0.90 as primary on this exact trace. That would
have sent the engineer to inspect the inventory-service 503, which
*was real* but *wasn't the cause of the test failure*. The
abstention preserved trust.

**What the engineer should do:** Read all three candidates. The
report puts `latency_vs_db` last by severity ranking, but its
confidence is highest — that's the actionable signal.

This is the canonical hard case. It is preserved as a regression
test ([test_calibration_benchmark.py](../arip-core/tests/test_calibration_benchmark.py)).

---

## Trust pattern across all four

In every abstention case above, the engine:

1. States **why** it abstained, in plain language
2. Names the abstention **code** for programmatic use
3. Lists the **diagnostics** that pinpoint the missing/conflicting signal
4. Where applicable, shows the **candidate** findings the engineer can
   weigh manually

It does NOT:

- Apologise for not having a hypothesis
- Suggest a confidence-padded primary "just to have one"
- Bury the abstention beneath a TL;DR that sounds confident

That last property is what makes the engine usable as a CI surface.
A primary hypothesis means *the engine is willing to stand behind
this*. An abstention means *engine is being honest about uncertainty*.
Either is useful; the dangerous middle would be confident-sounding
guesses.

## Related reading

- [CALIBRATION.md](CALIBRATION.md) — the trust contract that abstention enforces
- [INVESTIGATION_RULES.md](INVESTIGATION_RULES.md) — the rule registry that produces evidence
- [calibration-gallery.md](calibration-gallery.md) — readable narratives of the calibration benchmark
- [examples/abstention.md](examples/abstention.md) — the verbatim no_primary_trace example
