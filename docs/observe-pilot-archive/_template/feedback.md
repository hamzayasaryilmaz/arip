# Operator feedback — `op<id>`

_The operator's own words. Direct quotes only. Pilot runner's
interpretation belongs in `operator-notes.md`._

## First-impression quote

> _"<verbatim, one to three sentences>"_

## Question that pinned it

After the operator finished reading, the pilot runner asked **one**
of the questions below. Record which question was asked and the
verbatim answer.

> Q: `<one of>`
> - "Did you find a recurring pattern you didn't already know about?"
> - "Was the digest more or less useful than `tail -f logs.json | jq`?"
> - "Would you run this against next week's CI telemetry without
>   being asked?"
> - "What part of this digest made you reach for another tool?"
>
> A: `<verbatim answer>`

## Trust questions

For each rule-grounded cluster the operator examined:

| Cluster (rule) | "Do you trust this?" answer (verbatim) |
|---|---|
| `<rule_id>` | `<...>` |

For each abstention cluster the operator examined:

| Cluster (code) | "Was this abstention honest or evasive?" (verbatim) |
|---|---|
| `<abstention_code>` | `<...>` |

If the operator did not engage with a cluster, write **"not read"**.

## "I would..."

The operator's verbatim answer to *"if you ran this against your
own team's telemetry this week, what would you do with the digest?"*

> `<verbatim>`

If the answer is "nothing", that's a useful signal. Don't sanitise.

## Off-limits questions raised

Things the operator asked for that are explicitly out-of-scope for
Phase A. Verbatim quote, then a one-line route to where the request
already lives:

- "_<quote>_" → `<FUTURE_ARCHITECTURE.md #11 trigger / POSITIONING.md anti-goal / not on roadmap>`

## Closing question

> Q: "On a scale of 'I'd ignore this' to 'I'd open this every
>     Monday', where does this digest sit for you?"
>
> A: `<verbatim>`

## Trust regression flag

- [ ] No trust regression observed
- [ ] Possible trust regression — see Finding `<N>` in
      `usability-findings.md`
- [ ] **Confirmed trust regression — release blocker.** Engine
      produced a confidently-wrong cluster. STOP further pilots.
      File issue immediately.
