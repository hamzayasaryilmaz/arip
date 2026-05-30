# Common objections — honest answers

Your private reference for handling pushback in CTO/eng-lead
meetings. Each objection has the **honest** answer, not the sales
answer. The honest answers are stronger because they don't
overpromise.

Read this before each pitch. Do NOT print this for the customer.

---

## "We already have Datadog / Honeycomb / New Relic. Why ARIP?"

**Honest answer:**

> Datadog/Honeycomb/NR are observability **platforms** — they
> store and query telemetry. ARIP is an **investigation
> reasoning engine** — it consumes telemetry from one of those
> backends and applies rules to produce a per-failure report.
>
> They don't compete. If you uninstall Datadog, ARIP stops
> working (no data to consume).
>
> The thing ARIP does that Datadog doesn't: when a test fails,
> automatically traverse the trace + logs + DB queries and
> produce a markdown report that says "look here, this is most
> likely why" with cited evidence. Datadog gives you a UI to
> traverse manually. ARIP does the traversal and produces a PR
> comment.

**Follow-up if they push:**

> "If Datadog already does what you need, ARIP is wrong tool.
> ARIP only makes sense if you find yourself or your team
> spending hours manually tracing through Datadog UI for the
> same patterns over and over."

---

## "Is this AI? AI tools hallucinate."

**Honest answer:**

> No AI in the analysis path. Five fixed Python rules — you can
> read each in 200 lines. The reasoning is deterministic: same
> input always produces same output.
>
> There IS an optional LLM step that paraphrases the report's
> TL;DR — like a cover letter on top of a deterministic
> investigation. The LLM never sees raw telemetry, never
> influences the verdict. If you don't set an API key, ARIP
> runs without the LLM entirely — the report is just slightly
> less friendly.
>
> The "AI hallucinates" problem applies to tools where AI does
> the reasoning. ARIP's reasoning is grep + walk-the-tree +
> apply-five-rules. No model in the loop.

---

## "5 rules sounds limiting. Our failures don't fit those patterns."

**Honest answer:**

> You're probably right for some failures. The rules cover:
> retry storms, DB pool exhaustion, downstream errors,
> concurrent modification, latency-dominated-by-DB. If your
> failures are mostly "some logic bug we wrote" or "a flaky
> external dependency that doesn't propagate errors", ARIP
> will abstain on those — honestly say "I don't have a rule
> for this".
>
> That's actually the design. We refuse to add rules
> speculatively. Each new rule requires a calibration
> benchmark scenario to prove it doesn't produce false
> positives.
>
> Two paths if this matters:
> 1. Run the paid pilot. If 80% of your failures abstain, ARIP
>    isn't a fit and you'll know within 2 weeks.
> 2. If you have a recurring failure pattern that's NOT one of
>    the 5 rules, the engagement can include developing a
>    custom rule for it. Costs extra ($2-4k per rule), and
>    requires a calibration benchmark scenario.

**Follow-up:**

> "What failure pattern do you keep investigating manually that
> doesn't fit those 5?"
>
> If they describe something concrete and recurring, that's an
> interesting candidate for a custom rule + paid engagement.

---

## "We use [Splunk / New Relic APM / AWS X-Ray] — does ARIP support it?"

**Honest answer:**

> ARIP natively supports Jaeger, Tempo, Loki, and Elasticsearch.
> For other backends, the adapter pattern is the same — a small
> Python script that reads the backend's format and outputs the
> JSONL trace-bundle format ARIP consumes. Each new adapter is
> 1-2 days of work.
>
> If your backend isn't on the supported list, the paid pilot
> can include the adapter. I bill it as part of the engagement.
> Cost: typically +$2-3k on top of the base pilot price.

**Specific by backend:**

| Backend | Status |
|---|---|
| Jaeger | ✓ Native |
| Tempo | ✓ Native |
| Loki | ✓ Native |
| Elasticsearch (APM Server, OTel-via-ES) | ✓ Native |
| Honeycomb | ✓ OTLP-compatible |
| Grafana Cloud Tempo | ✓ Tempo adapter + cloud auth |
| AWS X-Ray | ✓ Via segment converter |
| Datadog APM | Adapter not yet shipped — buildable in 1-2 days |
| New Relic APM | Adapter not yet shipped — buildable in 1-2 days |
| Splunk APM | Adapter not yet shipped — buildable in 1-2 days |
| AppDynamics | Adapter not yet shipped — needs paradigm mapping |
| Dynatrace | Adapter not yet shipped — OneAgent complicates |
| Logs-only setup (no tracing) | **Won't work** — ARIP requires distributed tracing |

---

## "How does this compare to incident management tools like Rootly / FireHydrant / Blameless?"

**Honest answer:**

> Different layer. Those tools manage the incident response
> workflow — paging, war rooms, post-mortems. ARIP automates
> the technical investigation step that often happens BEFORE
> the incident is even declared (a CI failure that's actually
> a regression).
>
> Incident tools sit above ARIP in the stack. They're
> complementary, not competitive.

---

## "Can we self-host this on Kubernetes?"

**Honest answer:**

> Today: it's a Python CLI + SQLite. Run it locally, in a
> Docker container, or as a GitHub Actions step. There's a
> reference GHA workflow in the repo.
>
> A K8s operator is on the FUTURE_ARCHITECTURE roadmap (item
> 3) but trigger-gated — we won't build it until at least one
> real customer needs it. If you specifically need a K8s
> operator, that's a conversation: I can scope it as a paid
> engagement (~$10-20k for a basic operator).

---

## "What's the SLA / support model?"

**Honest answer:**

> Three tiers:
>
> 1. **OSS only**: no SLA, no support — bug reports via GitHub
>    issues, responded to when I have time. This is free.
>
> 2. **Integration engagement (Offering A)**: includes a 30-day
>    bug-fix window after delivery. Beyond that, ad-hoc paid
>    hourly support.
>
> 3. **Annual support contract (Offering D)**: 48h response on
>    business hours, 24h on critical. Security patch backports
>    within 7 days of upstream fix. Available after you've been
>    a customer for 60+ days.
>
> No 24/7 on-call. No 99.999% uptime guarantee. The product is
> the deterministic engine; the support is from one engineer
> with limited hours.

---

## "Is this funded? VC-backed? What's the company structure?"

**Honest answer:**

> No, not funded. I built this. It's open-source on my GitHub.
> I offer commercial services around it. No company structure
> yet — if we close on an engagement, I'll incorporate (LLC or
> equivalent) before we sign the SOW.

**If they push on "what if you disappear?":**

> "ARIP is Apache-2.0 OSS. If I disappear tomorrow, you can
> fork it and continue. Every commit is on GitHub, every
> design decision is in the docs. The 6,000 lines of Python
> are auditable by your team in an afternoon. The risk profile
> is closer to 'using an OSS library' than 'using a vendor's
> proprietary product'."

---

## "What's your customer reference list?"

**Honest answer:**

> You'd be among the first. I'm actively running paid pilots —
> not enterprise contracts yet.
>
> What I can offer instead of references:
> - Public repo with full validation history
> - Detailed pilot archives showing how the engine behaves on
>   unknown systems (including HotROD and OTel Demo)
> - Calibration benchmark with 10 scenarios that documents
>   trust contract behavior
> - Validation track record: 2 real defects caught during
>   stress testing, both narrowly fixed with regression tests
>
> If you want to be in the first cohort, there's early-partner
> pricing (30-50% off) in exchange for a written case study
> after the engagement.

**If they want a reference:**

> "I'd rather build to a real reference than fake one. I can
> connect you with [other early customers in your industry/region]
> once I have them, if that's a deal-breaker. Until then,
> evaluate on the repo + demo."

---

## "How long is the implementation? When do we see value?"

**Honest answer:**

> Integration engagement: 2-4 weeks. First report on a real
> failure: within the first 3-5 days. Full coverage of your
> CI: end of week 2.
>
> Telemetry hygiene audit (Offering B): 1 week, deliverable
> is the report itself.
>
> Paid pilot (Offering C): 2 weeks total, with results visible
> in week 1.

---

## "What does this cost over 12 months?"

**Honest answer:**

| Scenario | Year 1 cost |
|---|---|
| OSS only, you self-integrate | $0 (your engineer time) |
| Integration engagement + DIY support | $5k-15k once |
| Pilot → integration → support contract | $25k-50k spread over the year |
| Custom rule development as needed | +$2-4k per rule |

> The expensive failure mode here is the SUPPORT contract — if
> you'd benefit from a 48h-response SLA on critical bugs, that
> alone is $12k-36k/year and you should compare it to your
> engineer time saved.
>
> Most customers don't need the support contract. Most need
> the integration engagement and then operate ARIP themselves.

---

## "Can we get a discount / free POC?"

**Honest answer:**

> Free POC isn't a good fit because it inverts the value
> dynamic — if it's free, your team won't invest in making it
> work, and we both lose.
>
> Real discount path: early partner pricing. 30-50% off any
> engagement in exchange for:
> - Written case study (you sign off on it before I publish)
> - Permission to reference you in pitches
> - 30 minutes of post-engagement Q&A about what worked / didn't

---

## "What if we're not happy with the engagement?"

**Honest answer:**

> For Offerings A and C: I'll write into the SOW that if you
> don't accept the deliverables (i.e., I missed scope), 50%
> refund. If you accept but choose not to roll out, no refund
> — you got the audit and integration sketch which are
> independently valuable.
>
> For Offering B (audit): full refund if the report contains
> demonstrable factual errors. Caveat: "I don't agree with
> the prioritization" doesn't qualify as a factual error.
>
> I'm a single consultant, not an enterprise vendor — these
> terms reflect that I can't absorb a $20k loss the way a
> funded company can.

---

## "Why is this open source if you're commercializing?"

**Honest answer:**

> Trust. The whole positioning is "deterministic engine you
> can audit". If you can't read the code, you can't trust the
> abstention discipline. OSS is the only honest delivery
> mechanism for that promise.
>
> Commercial revenue covers integration, customization,
> support — not the software itself. This is a healthy OSS
> model (see Sentry, ClickHouse, PostHog as parallels) where
> the source code is the proof of trustworthiness, not the
> revenue source.

---

## "Show me a demo."

**Honest answer:**

> Easiest path: `git clone` the repo, run `bin/arip-demo.sh`.
> 30 seconds to a full demo on your laptop. I can sit with you
> while you do it.
>
> A pre-recorded demo video would just be that, but with my
> commentary. Less educational than running it yourself.

**If they insist on a recording:**

> "I deliberately haven't recorded one because every demo
> video I've seen for tools like this overstates capability.
> I'd rather you see ARIP abstaining on a real edge case in
> the live demo than see a polished happy-path video.
> If you really want me to record one, +$2k on the
> engagement and I'll do it as part of customer enablement."

---

## "What's the catch?"

**Honest answer:**

> The catch is: ARIP's value depends entirely on your
> telemetry quality. If your distributed tracing is solid,
> ARIP works well. If your tracing is patchy, ARIP will
> abstain a lot — which is honest, but it's not what most
> customers want to hear.
>
> That's why Offering B (audit) is often the right first
> engagement. Better to find out your telemetry isn't ready
> than to pay for an integration that abstains on 80% of
> failures.

---

## Closing line (use sparingly)

When you sense the meeting is wrapping up:

> "If you walk away from this conversation only one thing,
> walk away with: ARIP refuses to give a wrong answer. That's
> the whole product. Everything else — the 5 rules, the
> adapters, the cluster store — is implementation detail of
> that one promise."
