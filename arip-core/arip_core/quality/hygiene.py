"""Telemetry-hygiene findings.

Runs AFTER `prerequisite.check_prerequisites` passes. The prereq
gate decides whether ARIP can run at all; this module surfaces
*specific* gaps in the telemetry that would let more rules fire or
make existing rules more reliable.

Each finding is a single string describing one concrete issue and
the action the operator can take. Findings are operator-facing
(printed in digests, exposed via CLI) — they do NOT change engine
reasoning.

Four checks:
  1. Span-tree gaps — parent_span_id points outside the bundle,
     suggesting an uninstrumented intermediate service.
  2. Service-coverage assertion — operator's declared
     `expected_services_per_trace` not all present.
  3. Log-source completeness — operator's declared
     `expected_log_sources` not all present.
  4. Business-key propagation — entry-point span has business_key,
     but downstream spans don't carry it (so cross-trace correlation
     by that key won't work for this request).
"""

from __future__ import annotations

from ..canonical.config import NormalizationConfig
from ..correlator.models import CorrelatedTelemetry


def collect_hygiene_findings(ct: CorrelatedTelemetry, config: NormalizationConfig) -> list[str]:
    """Return human-readable hygiene findings for this telemetry slice.

    Empty list = clean. Operators read this list to know what to
    instrument next.
    """
    findings: list[str] = []
    findings.extend(_span_tree_gap_findings(ct))
    findings.extend(_service_coverage_findings(ct, config))
    findings.extend(_log_source_findings(ct, config))
    findings.extend(_business_key_propagation_findings(ct, config))
    return findings


def _span_tree_gap_findings(ct: CorrelatedTelemetry) -> list[str]:
    """Detect orphan spans whose parents are absent from the bundle.

    In practice, orphans mean either (a) the parent was sampled out,
    (b) the upstream service isn't OTel-instrumented, or (c) header
    propagation broke at some boundary. ARIP can't tell which —
    surfaces the gap and lets the operator decide.
    """
    span_ids = {s.span_id for s in ct.spans if s.span_id}
    orphans = [s for s in ct.spans if s.parent_span_id and s.parent_span_id not in span_ids]
    if not orphans:
        return []
    # Group orphans by the SERVICE that owns them — telling the
    # operator "service X has 5 orphan spans" is more actionable
    # than a flat count.
    by_service: dict[str, int] = {}
    for o in orphans:
        by_service[o.service_name] = by_service.get(o.service_name, 0) + 1
    services_str = ", ".join(f"{svc} ({n})" for svc, n in sorted(by_service.items()))
    return [
        f"Span-tree gap: {len(orphans)} orphan span(s) across "
        f"{len(by_service)} service(s) — {services_str}. "
        f"Their parent_span_id references spans NOT in the bundle. "
        f"Likely cause: an intermediate service is not OTel-instrumented, "
        f"or traceparent propagation breaks at a service boundary "
        f"(API gateway is the most common culprit)."
    ]


def _service_coverage_findings(ct: CorrelatedTelemetry, config: NormalizationConfig) -> list[str]:
    """Operator-declared service-coverage assertion.

    Operator sets `expected_services_per_trace: [frontend, cart, ...]`
    in their NormalizationConfig. This check flags any trace where
    one of those services is missing — a strong signal that telemetry
    from that service isn't reaching ARIP."""
    expected = getattr(config, "expected_services_per_trace", None) or []
    if not expected:
        return []
    actual_services = {s.service_name for s in ct.spans if s.service_name}
    missing = [svc for svc in expected if svc not in actual_services]
    if not missing:
        return []
    return [
        f"Service-coverage gap: expected services {expected} per trace, "
        f"but {missing} are absent from this bundle. Either the trace "
        f"genuinely didn't touch them, or their telemetry isn't being "
        f"exported. If it's the latter, ARIP will systematically "
        f"under-represent failures involving those services."
    ]


def _log_source_findings(ct: CorrelatedTelemetry, config: NormalizationConfig) -> list[str]:
    """Operator-declared log-source completeness.

    Operator sets `expected_log_sources: [frontend, payment, ...]`.
    Check that logs from each of those services are present in the
    bundle. Missing = the Loki/ES adapter didn't pull or the service
    isn't logging — both telemetry-hygiene gaps."""
    expected = getattr(config, "expected_log_sources", None) or []
    if not expected:
        return []
    actual_sources = {l.service_name for l in ct.logs if l.service_name}
    if not actual_sources:
        return [
            f"Log-source gap: 0 log entries in this bundle. Expected "
            f"logs from {expected}. Either the log adapter wasn't run "
            f"(see Workflow 2 in INGESTION_GUIDE.md) or none of these "
            f"services are logging during the failure window. Engine "
            f"will hit MIN_EVIDENCE_KINDS=2 abstention more often."
        ]
    missing = [svc for svc in expected if svc not in actual_sources]
    if not missing:
        return []
    return [
        f"Log-source gap: expected logs from {expected}, present "
        f"from {sorted(actual_sources)}. Missing: {missing}. "
        f"Either these services aren't emitting logs or their logs "
        f"aren't being pulled into the bundle (check your Loki/ES "
        f"query filters)."
    ]


def _business_key_propagation_findings(
    ct: CorrelatedTelemetry, config: NormalizationConfig
) -> list[str]:
    """Check that the entry-point span's business_key (if any)
    propagates to at least one downstream span. If not, cross-trace
    correlation by that key won't work for this request — ARIP will
    miss the linked sibling traces (webhook race, etc.)."""
    if not config.business_key_attrs:
        return []
    span_ids = {s.span_id for s in ct.spans if s.span_id}
    entry_spans = [s for s in ct.spans if not s.parent_span_id or s.parent_span_id not in span_ids]
    if not entry_spans:
        return []
    # Build the canonical signal accessor once.
    signals = ct.signals
    findings: list[str] = []
    for entry in entry_spans:
        entry_key = signals.business_key_for(entry)
        if not entry_key:
            continue
        # Find downstream spans (children of this entry).
        downstream = [s for s in ct.spans if s.span_id != entry.span_id]
        if not downstream:
            continue
        # At least one downstream should carry the SAME key.
        downstream_carries = any(signals.business_key_for(s) == entry_key for s in downstream)
        if not downstream_carries:
            findings.append(
                f"Business-key propagation gap: entry-point span "
                f"`{entry.operation_name}` on `{entry.service_name}` "
                f"carries business key but downstream spans don't. "
                f"Cross-trace correlation by this key won't link "
                f"sibling traces (webhook/async-event flows would be "
                f"silently missed). Ensure downstream services include "
                f"the business key in their span attributes."
            )
            break  # one finding is enough — no spam per trace
    return findings
