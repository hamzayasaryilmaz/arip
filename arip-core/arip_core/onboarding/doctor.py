"""`arip doctor`: per-rule diagnostic against a real bundle.

For each of the 5 shipped rules, the doctor checks the operator's
sample telemetry against the rule's required + optional signals and
reports:

  - whether the rule WOULD fire on this sample (and how often)
  - which required signals are present / missing
  - which optional signals would lift confidence if added
  - one concrete next step the operator can take

Replaces the "I ran arip and nothing happened, what now?" failure
mode with "here's exactly which signal is missing for each rule."
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..canonical.config import NormalizationConfig
from ..correlator.models import CorrelatedTelemetry
from ..engine.hypothesis import investigate
from ..quality.contracts import RULE_CONTRACTS


@dataclass
class RuleDiagnostic:
    rule_id: str
    description: str
    would_fire: bool
    primary_count: int
    abstain_count: int
    signal_presence: dict[str, bool]  # signal name → present in sample
    blocker: str | None  # one-line reason rule won't promote (if applicable)
    next_step: str | None


@dataclass
class DoctorReport:
    samples: int
    spans: int
    logs: int
    services: list[str] = field(default_factory=list)
    rules: list[RuleDiagnostic] = field(default_factory=list)
    overall_signals: dict[str, str] = field(default_factory=dict)


# ─── Signal probes ────────────────────────────────────────────────────
#
# These mirror the names in quality/contracts.py. Each returns True/False
# given a sample list of CorrelatedTelemetry. Reflects what the rule
# would actually look for at evaluate-time.


def _has_business_keys(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        if ct.signals.business_keys_enabled():
            for s in ct.spans:
                if ct.signals.business_key_for(s):
                    return True
    return False


def _has_state_transitions(samples: list[CorrelatedTelemetry]) -> bool:
    cfg = samples[0].normalization_config if samples else NormalizationConfig()
    target = getattr(cfg, "state_transition_event_name", "") or "state.transition"
    for ct in samples:
        for s in ct.spans:
            for ev in s.events or []:
                name = ev.get("name") if isinstance(ev, dict) else getattr(ev, "name", "")
                if name == target:
                    return True
    return False


def _has_retry_attempt(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        for s in ct.spans:
            if ct.signals.retry_attempt(s) is not None:
                return True
    return False


def _has_log_level(samples: list[CorrelatedTelemetry], levels: tuple[str, ...]) -> bool:
    upper = {l.upper() for l in levels}
    for ct in samples:
        for l in ct.logs:
            if (l.level or "").upper() in upper:
                return True
    return False


def _has_span_error_status(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        for s in ct.spans:
            if s.is_error:
                return True
    return False


def _has_cross_service_chain(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        by_id = {s.span_id: s for s in ct.spans}
        for s in ct.spans:
            if not s.parent_span_id:
                continue
            p = by_id.get(s.parent_span_id)
            if p and p.service_name and p.service_name != s.service_name:
                return True
    return False


def _has_db_pool_stats(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        for s in ct.spans:
            attrs = s.attributes or {}
            if any(k.startswith("db.pool.") for k in attrs):
                return True
    return False


def _has_handler_span(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        for s in ct.spans:
            if ct.signals.is_handler_span(s):
                return True
    return False


def _has_db_child(samples: list[CorrelatedTelemetry]) -> bool:
    for ct in samples:
        for s in ct.spans:
            if ct.signals.is_db_span(s):
                return True
    return False


_PROBES = {
    "business_keys": _has_business_keys,
    "state_transitions": _has_state_transitions,
    "retry_attempt": _has_retry_attempt,
    "warn_logs": lambda s: _has_log_level(s, ("WARN", "WARNING")),
    "error_logs": lambda s: _has_log_level(s, ("ERROR",)),
    "span_error_status": _has_span_error_status,
    "service_boundary": _has_cross_service_chain,
    "http_status": lambda s: any(
        any(k in ("http.status_code", "http.response.status_code") for k in (sp.attributes or {}))
        for ct in s
        for sp in ct.spans
    ),
    "db_pool_stats": _has_db_pool_stats,
    "db_query_span": _has_db_child,
    "handler_span_identifiable": _has_handler_span,
    "db_child_span": _has_db_child,
    # placeholders for nuance the doctor doesn't claim to prove
    "retry_reason": lambda s: any(ct.signals.retry_reason(sp) for ct in s for sp in ct.spans),
    "retry_backoff_ms": lambda s: any(
        ct.signals.retry_backoff_ms(sp) is not None for ct in s for sp in ct.spans
    ),
    "retry_max_attempts": lambda s: any(
        ct.signals.retry_max_attempts(sp) is not None for ct in s for sp in ct.spans
    ),
    "empty_acquires_total": lambda s: any(
        "db.pool.empty_acquires_total" in (sp.attributes or {}) for ct in s for sp in ct.spans
    ),
}


_BLOCKER_HINTS = {
    "business_keys": (
        "your NormalizationConfig has business_key_attrs=[]. Add "
        "`business_keys: [<your-id-attr>]` so cross-service correlation works."
    ),
    "state_transitions": (
        "no spans carry a `state.transition` event. Emit one when "
        "your service mutates the business entity's state — without it, "
        "the rule cannot confirm both sides actually wrote."
    ),
    "retry_attempt": (
        "no span carries the `retry.attempt` attribute. Tag each retry "
        "loop body with `span.set_attribute('retry.attempt', N)`."
    ),
    "span_error_status": (
        "no span has ERROR status. Either no failures occurred in this "
        "sample, or your instrumentation isn't propagating exceptions "
        "to the span (check OTel's record_exception / set_status)."
    ),
    "service_boundary": (
        "all spans are in one service. Multi-service rules need at least "
        "two services in the same trace — check traceparent propagation."
    ),
    "db_pool_stats": (
        "no span carries `db.pool.*` attributes. The rule is deliberately "
        "strict to avoid false positives — your connection pool wrapper "
        "must explicitly export `db.pool.acquired`, `db.pool.max`, "
        "`db.pool.wait_ms` to make this rule fire."
    ),
    "handler_span_identifiable": (
        "no span's operation_name matches your handler_operation_patterns. "
        "Defaults cover `POST /`, `GET /`, etc.; override in config if "
        "your services name handlers differently."
    ),
    "db_child_span": (
        "no span operation matches your DB pattern. By default ARIP looks "
        "for `db.` prefix; override `db.operation_patterns` if your DB "
        "instrumentation uses different names."
    ),
}


def diagnose(samples: list[CorrelatedTelemetry]) -> DoctorReport:
    """Run the per-rule diagnostic against `samples`."""
    report = DoctorReport(
        samples=len(samples),
        spans=sum(len(ct.spans) for ct in samples),
        logs=sum(len(ct.logs) for ct in samples),
    )
    report.services = sorted(
        {sp.service_name for ct in samples for sp in ct.spans if sp.service_name}
    )

    # Probe every signal once up-front so we don't redo work per rule.
    signal_results: dict[str, bool] = {name: probe(samples) for name, probe in _PROBES.items()}

    # Run the engine to see who fires on real data.
    fire_counts: Counter[str] = Counter()
    abstain_counts: Counter[str] = Counter()
    for ct in samples:
        try:
            r = investigate(ct)
        except Exception:
            continue
        if r.primary and r.primary.rule_id:
            fire_counts[r.primary.rule_id] += 1
        for h in r.all_ranked:
            if h.rule_id and h.rule_id not in fire_counts:
                abstain_counts[h.rule_id] += 1

    # Combine with contract for the per-rule story.
    for c in RULE_CONTRACTS:
        presence = {
            sig: signal_results.get(sig, False) for sig in c.required_signals + c.optional_signals
        }
        missing_required = [sig for sig in c.required_signals if not signal_results.get(sig)]
        blocker = None
        next_step = None
        if missing_required:
            sig = missing_required[0]
            blocker = f"missing required signal: `{sig}`"
            next_step = _BLOCKER_HINTS.get(
                sig, "see docs/INVESTIGATION_RULES.md for this signal's contract"
            )
        report.rules.append(
            RuleDiagnostic(
                rule_id=c.rule_id,
                description=c.description,
                would_fire=fire_counts[c.rule_id] > 0,
                primary_count=fire_counts[c.rule_id],
                abstain_count=abstain_counts[c.rule_id],
                signal_presence=presence,
                blocker=blocker,
                next_step=next_step,
            )
        )

    report.overall_signals = {k: "present" if v else "missing" for k, v in signal_results.items()}
    return report


def render_doctor_report(report: DoctorReport) -> str:
    """Render a DoctorReport as operator-readable markdown."""
    lines: list[str] = []
    add = lines.append

    add("# ARIP doctor — telemetry shape diagnostic\n")
    add(
        f"_inspected {report.samples} trace(s), {report.spans} spans, "
        f"{report.logs} logs across {len(report.services)} service(s):_ "
        f"{', '.join(report.services) if report.services else '(none)'}\n"
    )

    ready = sum(1 for r in report.rules if r.would_fire)
    add(f"## Summary: {ready}/{len(report.rules)} rules would fire on this sample\n")

    add("| Rule | Status | On this sample | Why |")
    add("|---|---|---|---|")
    for r in report.rules:
        if r.would_fire:
            status = "✅ ready"
            why = f"fired primary {r.primary_count}× and abstained {r.abstain_count}× in sample"
        elif r.blocker is None:
            status = "⚠️ silent"
            why = "rule did not match on this sample (no failures of this kind present, or only abstained)"
        else:
            status = "❌ blocked"
            why = r.blocker
        add(f"| `{r.rule_id}` | {status} | primary={r.primary_count} | {why} |")
    add("")

    # Per-rule detail for rules that aren't ready
    blocked = [r for r in report.rules if r.blocker]
    if blocked:
        add("## Blockers + next steps\n")
        for r in blocked:
            add(f"### `{r.rule_id}` — {r.description}\n")
            add(f"**Blocker:** {r.blocker}\n")
            add(f"**Next step:** {r.next_step}\n")
            add("**Required signals on this sample:**")
            from ..quality.contracts import contracts_for_rule

            contract = contracts_for_rule(r.rule_id)
            if contract:
                for sig in contract.required_signals:
                    mark = "✅" if r.signal_presence.get(sig) else "❌"
                    add(f"- {mark} required: `{sig}`")
                for sig in contract.optional_signals:
                    mark = "✅" if r.signal_presence.get(sig) else "·"
                    add(f"- {mark} optional: `{sig}`")
            add("")

    add("## Overall signal census\n")
    present = sorted([k for k, v in report.overall_signals.items() if v == "present"])
    missing = sorted([k for k, v in report.overall_signals.items() if v == "missing"])
    add(f"**Present** ({len(present)}): {', '.join(f'`{s}`' for s in present) or '_none_'}")
    add("")
    add(f"**Missing** ({len(missing)}): {', '.join(f'`{s}`' for s in missing) or '_none_'}")
    add("")
    add("---")
    add(
        "\nNext: edit your NormalizationConfig to match the blocked rules' "
        "expectations, or use `arip init --from <BUNDLE> --out arip.yaml` "
        "to auto-generate a starter config from this telemetry."
    )

    return "\n".join(lines)
