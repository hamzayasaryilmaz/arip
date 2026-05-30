# Commercial offerings

ARIP is Apache-2.0 OSS. This document is the **honest** commercial
positioning: what you can sell around the OSS, at what price points,
with what deliverables.

It is NOT a marketing brochure. It is a working reference for the
operator-as-vendor — the engineer who's offering ARIP-based services
to companies. Phrasing here is what you'd put in a Statement of Work
or SOW, not in a sales deck.

## What's actually for sale

ARIP itself is free. What you sell:

1. **Integration + setup expertise** — install ARIP correctly in a
   customer's CI pipeline against their specific telemetry stack.
2. **Telemetry hygiene audit** — use ARIP's prerequisite gate +
   hygiene findings to produce a report on what the customer's
   telemetry is missing. Valuable on its own.
3. **Ongoing support contract** — SLA-backed response to bugs +
   custom rule development.
4. **Paid pilot engagement** — 2-week engagement that gives the
   customer real value AND gives the project the real-engineer
   pilot data Phase 2 entry gate needs.
5. **Custom adapter development** — when a customer uses a vendor
   ARIP doesn't yet adapt (Datadog APM, New Relic APM, Splunk APM),
   build the adapter as part of the engagement.

## Four offerings, by complexity

### Offering A — Integration engagement

> "I install and configure ARIP in your CI/staging pipeline."

| | |
|---|---|
| **Duration** | 2-4 weeks |
| **Price range** | $5,000–$15,000 |
| **Deliverables** | Working `arip investigate` in CI + 1 sticky-PR comment example + custom `NormalizationConfig` + team training (1 hour) + 30-day bug-fix window |
| **Best for** | Customers who have OTel + Jaeger/Tempo already running and want to bolt on RCA reporting |
| **Prerequisites** | Customer has distributed tracing; customer has Playwright OR Cypress CI |
| **Risk** | Low — ARIP is OSS, customer can fork if you disappear |
| **SOW template** | `docs/templates/INTEGRATION_ENGAGEMENT.md` |

### Offering B — Telemetry hygiene audit

> "I run ARIP's prerequisite gate + hygiene findings against your
> telemetry and write up what's missing."

| | |
|---|---|
| **Duration** | 1 week |
| **Price range** | $3,000–$8,000 |
| **Deliverables** | 10-page report: prerequisite check result, span-tree gap analysis, service-coverage analysis, business-key propagation analysis, log-source completeness analysis, prioritized fix list, ARIP-readiness assessment |
| **Best for** | Customers who suspect their observability is incomplete; OR customers evaluating ARIP and want a low-commitment first engagement |
| **Prerequisites** | Customer can export 1 hour of telemetry to a file ARIP can read |
| **Risk** | Lowest — pure deliverable, no install required |
| **SOW template** | `docs/templates/TELEMETRY_HYGIENE_AUDIT_REPORT.md` |

### Offering C — Paid pilot

> "I run a full ARIP pilot against your telemetry — including
> setup, observation digest, integration sketch, and honest
> assessment of whether ARIP fits your stack."

| | |
|---|---|
| **Duration** | 2 weeks |
| **Price range** | $5,000–$10,000 |
| **Deliverables** | Working ARIP integration + 1-week observation digest + telemetry hygiene audit (Offering B's report) + honest GO/NO-GO recommendation + (if GO) next-step proposal for Offering A |
| **Best for** | Customers evaluating ARIP for production rollout; YOUR commercial path to gather real-engineer pilot data |
| **Prerequisites** | Customer has distributed tracing OR willing to instrument; customer has 1 engineer who can spend 2-3 hours over the pilot |
| **Risk** | Moderate — you commit to a real working integration |
| **Why this is special** | This is the engagement that **closes the project's biggest gap** (Phase 2 entry gate needs ≥ 3 real-engineer pilots) AND generates revenue. Customer gets value either way. **Recommended starting offering.** |
| **SOW template** | `docs/templates/PAID_PILOT_SOW.md` |

### Offering D — Ongoing support contract

> "You self-host ARIP. I provide bug-fix SLA, security patches,
> custom rule development, and quarterly tuning."

| | |
|---|---|
| **Duration** | Annual, auto-renew |
| **Price range** | $12,000–$36,000/year ($1k–$3k/month) |
| **Deliverables** | Bug response: 48h business hours, 24h critical; security patch backports within 7 days of upstream fix; up to 4 custom rule developments/year; quarterly NormalizationConfig tuning; named escalation contact |
| **Best for** | Established ARIP users (i.e., customers who already went through Offering A or C) |
| **Prerequisites** | Customer has been using ARIP for ≥ 60 days |
| **Risk** | Moderate — you're locked in to response SLAs |
| **Don't offer until** | You have ≥ 2 customers and have run at least one bug-fix cycle |

## Pricing rationale (the honest version)

Anchors:

- **A senior observability consultant day-rate**: $1,500–$3,000/day
  in US/EU markets, $500–$1,000/day in TR market.
- **ARIP-specific knowledge**: small premium over generic consultant
  because the trust-contract discipline + 5-rule mental model is
  niche.
- **Customer's pain**: a flaky CI investigation typically costs 4–8
  engineer-hours per incident. At a $100/hr loaded engineer rate,
  that's $400–$800/incident. If ARIP saves even 5 incidents in the
  first month, the integration engagement pays for itself.

How to position price:

> "It's roughly equivalent to losing one senior engineer for a week
> to investigation work. The integration is a one-time cost."

Don't lead with price. Lead with the trust contract framing
(deterministic, refuses to guess, you can audit every claim).
Price is the second conversation.

## Discount policy

- **First 3 customers**: 30–50% discount in exchange for written
  case study + permission to use as reference. Frame as "early
  partner pricing".
- **Open-source projects** (apache foundation, CNCF, etc.):
  free Offering B, paid Offering A only if they want maintained
  integration.
- **Conference talks/blog posts about the engagement**: 20% discount.

Discount is leverage to get **proof points** (case studies,
references). Not a sales tactic.

## What you do NOT sell

These all violate either project anti-goals OR commercial discipline:

| Don't sell | Why |
|---|---|
| "Enterprise license" for the OSS | Apache-2.0 prohibits charging for the software itself; charge for services around it |
| "Premium tier" with feature gating | Breaks OSS community trust + splits the codebase |
| Hosted SaaS (in early days) | Massive ops investment; no customer demand yet; would compromise the no-dashboard anti-goal |
| Custom dashboards / UIs | Anti-goal #1 in POSITIONING.md |
| Auto-remediation services | Anti-goal |
| "ARIP integrates with your Slack alerting" | Anti-goal — ARIP is read-only by contract |
| Annual contracts before customer has run ARIP for 60+ days | Sets expectations you can't meet |
| Discounted "trial" without a Statement of Work | Sets up "free POC" expectation — every CTO loves this, every consultant regrets it |

## How to introduce yourself in a CTO meeting

Use the script in `docs/ARIP_ONE_PAGER.md`. Three-paragraph version:

> "I built an open-source deterministic CI investigation tool.
> Test fails → 30-second markdown report instead of 2 hours of
> log spelunking. No AI in the analysis path. Five fixed rules.
> Refuses to guess when it doesn't know. Apache-2.0, public on
> GitHub.
>
> I'm running paid pilots now. Want to be one? 2 weeks, $5–10k.
> Deliverable: working integration + telemetry hygiene audit
> report. Audit report alone is worth the engagement even if you
> decide ARIP isn't a fit.
>
> Honest caveats up front: needs distributed tracing (no OTel =
> can't help), 5 rules won't cover every failure (engine abstains
> instead of guessing), not a Datadog replacement (consumes from
> them, doesn't compete)."

That's the entire pitch. No deck, no demo video, no pricing
spreadsheet. The customer either wants a paid pilot or they
don't.

## The qualifier questions (use these in the first call)

Before quoting price, find out:

1. Do you have OpenTelemetry tracing in production?
   - Yes → continue
   - No → "ARIP can't help until you instrument. I do telemetry
     instrumentation engagements too if you want, but separate
     scope." (Offering B might still apply for the audit)
2. What test framework runs in CI?
   - Playwright/Cypress → ARIP integrates natively
   - Other → "ARIP's collector doesn't currently parse that. I
     can build the adapter as part of the pilot, +$2-3k."
3. What's the failure pattern you're trying to investigate faster?
   - Sounds like one of the 5 rules → "Likely fit"
   - Doesn't sound like any → "ARIP will abstain on these. That's
     honest, but means you won't get value from the rule clusters.
     The hygiene audit might still be useful. Want to think about
     it?"
4. Who would own ARIP internally after the engagement?
   - A named engineer → continue
   - "Whoever has time" → "I'd actually push back here. Without an
     owner, the integration will rot in 3 months. Let's revisit
     when you have someone."

Answers 1+4 are non-negotiable. 2+3 are scope-adjustable.

## What to take to the meeting

Three files. That's it.

1. `docs/ARIP_ONE_PAGER.md` — printed, leave behind
2. `docs/COMMON_OBJECTIONS_FAQ.md` — for your reference, not theirs
3. `docs/templates/PAID_PILOT_SOW.md` — fill out in real-time if
   they say yes

Do NOT take:
- A pitch deck
- A demo video
- A laptop running the demo (unless they explicitly ask)
- A pricing PDF

The product **is** the dürüst engineering pitch. Marketing collateral
undermines the trust positioning.

## Cross-references

- `docs/ARIP_ONE_PAGER.md` — leave-behind 1-pager
- `docs/COMMON_OBJECTIONS_FAQ.md` — honest objection handling
- `docs/templates/PAID_PILOT_SOW.md` — Offering C SOW template
- `docs/templates/INTEGRATION_ENGAGEMENT.md` — Offering A SOW template
- `docs/templates/TELEMETRY_HYGIENE_AUDIT_REPORT.md` — Offering B
  deliverable template
- `docs/PRODUCTION_DEPLOYMENT.md` — operator-side deployment guide
  (referenced in SOWs)
- `docs/POSITIONING.md` — anti-goals that gate commercial decisions
