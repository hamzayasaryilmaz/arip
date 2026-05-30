# op002b — NO HUMAN OPERATOR (runner-self-pilot continuation)

**This file does NOT contain operator feedback.** No human engineer
participated. Follow-up runner-self-pilot to op002, exploring:

**Context:** OTel Demo + fault injection ENABLED (paymentUnreachable, cartFailure, productCatalogFailure, recommendationCacheFailure, intlShippingSlowdown), Jaeger traces only (no log correlation)

See [docs/UNKNOWN_SYSTEMS_VALIDATION.md](../../UNKNOWN_SYSTEMS_VALIDATION.md)
for the cross-system synthesis (now including op002b + op002c findings).

## Does NOT count toward Phase 2 entry gate

op001/op002/op002b/op002c/op003 are all runner-self-pilots against
unknown OSS systems. The Phase 2 entry-gate quorum still requires
real engineers running observe-mode against their own telemetry.

The op002 ladder (op002 → op002b → op002c) is a deliberate
progression to test increasingly-rich telemetry shapes against the
same engine: healthy traffic → fault-injected traffic without log
correlation → fault-injected traffic with log correlation joined.

This progression makes a real validation point:
**MIN_EVIDENCE_KINDS=2 trust gate is real**, not theoretical.
Without log correlation, rule clusters do not fire even when the
underlying span data is correct. With log correlation, they do.
