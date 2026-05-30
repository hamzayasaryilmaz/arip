# Statement of Work — ARIP integration engagement

**Template — Offering A. Copy, fill, send.**

Pricing range for the operator (NOT in customer SOW):
$5,000–$15,000 depending on scope multipliers in Section 2.

Use this AFTER a successful paid pilot (Offering C) when customer
wants production rollout. Can also be used standalone if customer
has already self-evaluated ARIP from the demo + repo.

---

## Statement of Work — ARIP integration engagement

**Date:** `[YYYY-MM-DD]`
**Customer:** `[Customer Legal Name]`
**Customer contact:** `[Name, Title, Email]`
**Provider:** `[Your Name / Legal Entity]`
**Provider contact:** `[Your Name, Email]`

**Related SOW(s):** `[Reference paid-pilot SOW if applicable, e.g.,
"Customer completed paid pilot per SOW dated YYYY-MM-DD"]`

---

### 1. Background

Customer has decided to roll out ARIP (Apache-2.0, https://github.com/hamzayasaryilmaz/arip)
as a CI failure-investigation tool in their `[CI system]`
pipeline. This SOW covers the integration build, training, and a
30-day post-delivery bug-fix window.

### 2. Scope

Provider will:

1. **Production-ready ARIP integration into `[CI system]`.**
   - Update or create `.github/workflows/arip-investigate.yml`
     (or equivalent for `[GitLab CI / Jenkins / CircleCI / other]`)
   - Configure telemetry export from `[Jaeger / Tempo / Elasticsearch]`
     to ARIP at PR-time
   - Configure sticky PR comment on `[GitHub / GitLab / Bitbucket]`
   - Cache configuration for cross-run memory
2. **Custom NormalizationConfig** for Customer's environment:
   - Business keys: `[order.id / account_id / tenant_id / etc.]`
   - Business key aliases (if ID translation chain exists)
   - Expected services per trace: `[list]`
   - Expected log sources: `[list]`
   - Handler operation patterns: `[Controller# / /api/ / etc.]`
   - Retry / DB / state-transition attribute names if non-default
3. **Custom telemetry adapter** (only if Customer's backend is not
   in the natively supported list — Jaeger, Tempo, Loki,
   Elasticsearch, Honeycomb, Grafana Cloud, AWS X-Ray):
   - `[Specify the adapter to build, e.g., "Datadog APM trace export adapter"]`
4. **Training session (1 hour, recorded).**
   - Walkthrough of the integration
   - How to read an ARIP report
   - When ARIP abstains and why that's a feature
   - Operator-side documentation pointers
5. **30-day post-delivery bug-fix window.**
   - Bugs in the integration delivered: free fix within 5 business
     days of report
   - Beyond 30 days: ad-hoc paid hourly support OR migrate to
     ongoing support contract (Offering D)

**Scope multipliers for pricing (the operator decides):**

| Factor | Adjustment |
|---|---|
| Customer has Playwright AND Cypress | Base scope |
| Customer has a non-supported test framework | +$2-3k for adapter |
| Customer has a non-supported telemetry backend | +$2-3k for adapter |
| Custom rule development required | +$2-4k per rule (with calibration scenario) |
| Multi-environment deployment (dev + staging + prod) | +$2-3k |
| On-site delivery required | +$2k/day for travel |

### 3. Deliverables

| # | Deliverable | Format | Due |
|---|---|---|---|
| 1 | Production-ready CI workflow file(s) | Merged PR to Customer's repo | Week 1 end |
| 2 | NormalizationConfig YAML | Committed to Customer's repo (suggested path: `configs/arip/<env>.yaml`) | Week 1 end |
| 3 | Custom adapter (if applicable) | Operator-side script (`bin/`) committed to Customer's repo OR to ARIP's repo | Week 2 mid |
| 4 | First successful ARIP report on a real Customer failure | Sticky comment on a Customer PR | Week 2 end |
| 5 | Training session recording + handover doc | Video + 5-page operator handover doc | Week 3 mid |
| 6 | 30-day bug-fix window begins on Day 21 (after handover) | n/a | Days 21–51 |

### 4. Customer responsibilities

| | |
|---|---|
| Day 0 | Provide repository access; named engineering contact; CI admin contact |
| Day 1–5 | Approve NormalizationConfig draft; merge Provider's CI workflow PR |
| Day 6–10 | Allow ARIP to run against real PRs; provide read access to first 3-5 failure traces |
| Day 11–15 | Attend training session; designate ARIP "owner" engineer on Customer's team |
| Days 16+ | Customer's named owner operates ARIP; Provider in bug-fix-window-only mode |

### 5. Out of scope

- Production-grade scaling beyond Customer's existing CI throughput
- ARIP's hosted SaaS version (does not exist)
- Custom dashboard / web UI (not a feature of ARIP, anti-goal)
- Integration with Customer's alerting / paging tools (anti-goal)
- Migration from Customer's current observability vendor (separate
  consulting engagement)
- Training of more than 4 engineers (additional sessions at hourly
  rate)
- 24/7 emergency support (available only under Offering D contract)

### 6. Pricing + payment

**Total fixed price: $`[X]`** + scope multipliers from Section 2.

Payment schedule:
- 30% on signature: $`[Y]`
- 40% on Deliverable 4 (first real Customer failure investigation): $`[Y]`
- 30% on completion of handover (Deliverable 5): $`[Y]`

Payment terms: Net-30 from invoice date.

### 7. Timeline

| Phase | Days | Activity |
|---|---|---|
| Kickoff | Day 0 | SOW signed, kickoff call, access established |
| Build | Days 1–5 | CI workflow + NormalizationConfig (Deliverables 1, 2) |
| Adapter | Days 6–10 | Custom adapter if needed (Deliverable 3); else extra hardening |
| Validation | Days 11–15 | First real Customer failure → working ARIP report (Deliverable 4) |
| Handover | Days 16–20 | Training session + operator handover doc (Deliverable 5) |
| Bug-fix window | Days 21–51 | Free bug fixes on the integration delivered |

Total: 4 weeks active work + 4 weeks bug-fix window = 8 weeks total
relationship.

### 8. Acceptance

Customer accepts the engagement when:
1. Deliverable 4 is produced (ARIP successfully investigates a real
   Customer failure end-to-end)
2. Deliverable 5 is delivered (training + handover doc)
3. Customer's designated ARIP owner can run `arip investigate` and
   read the report without Provider intervention

Acceptance communicated in writing within 5 business days of
Deliverable 5. Silence = automatic acceptance.

### 9. IP, refunds, confidentiality, liability, governing law

Same as the paid-pilot SOW template (Sections 9–13 there).

Specific to this SOW:
- The CI workflow + NormalizationConfig developed are Customer's
  property; no Provider retention rights.
- Custom adapters MAY be contributed back to ARIP's upstream repo
  in generalized form, with Customer's written consent. Customer
  is credited if upstreamed.

### 10. Bug-fix window terms

Days 21–51 (30 days starting from Deliverable 5):

- **Bug**: integration behavior diverges from Provider's
  documented expected behavior, demonstrable by Customer.
- **Not a bug**: requests for new rules, new adapters, new
  features, configuration changes for new environments, ARIP
  upstream bugs (those go to GitHub issues).
- **Response time**: 5 business days for non-critical, 2 business
  days for critical (Customer's CI blocked).
- **Critical**: ARIP integration causes CI false-failures or
  blocks PR merges.
- **Beyond Day 51**: Customer can purchase additional support at
  $250/hr OR migrate to Offering D annual contract.

### 11. Signatures

| | Customer | Provider |
|---|---|---|
| Name | `[Name]` | `[Name]` |
| Title | `[Title]` | `[Title]` |
| Date | `[YYYY-MM-DD]` | `[YYYY-MM-DD]` |
| Signature | __________________ | __________________ |

---

## Operator notes (delete before sending)

**Successful integration looks like:**
- ARIP report appears on PRs automatically
- Customer's ARIP owner can run `arip investigate` locally
- At least one real Customer failure has been investigated end-to-end
- Customer's NormalizationConfig is committed to their repo (not
  living in your head)

**When to push back on scope:**
- "We want a dashboard" → Politely refuse, point to anti-goals
- "We want Slack alerts" → Same
- "We want to integrate with Jira" → Outside ARIP scope
- "We want it to fix things automatically" → Hard no
- "We want 24/7 support" → Offering D, separate contract

**When to upsell:**
- After Deliverable 4, if Customer is happy: introduce Offering D
- During Day 11-15, if you spot opportunities for custom rules:
  scope as separate SOW
- After Day 51, if Customer is still using ARIP heavily: propose
  Offering D
