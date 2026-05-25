"""Render an ``InvestigationReport`` as Markdown.

Deterministic: same report in, same bytes out. Sections rendered:

  * TL;DR (LLM if available, otherwise a deterministic line)
  * Abstention notice (when the engine declined to nominate a primary)
  * Cross-run context (history of the same fingerprint)
  * Flaky-test signal (per-test pass/fail rate)
  * Failure block
  * Primary hypothesis + evidence
  * Alternative hypotheses
  * Request timeline
  * Evidence index
"""

from __future__ import annotations

from io import StringIO

from ..engine.models import Evidence, Hypothesis
from .models import HistoryContext, InvestigationReport


def render(report: InvestigationReport) -> str:
    buf = StringIO()
    w = buf.write

    w(f"# Investigation Report — {report.failure.test_name}\n\n")
    w(
        f"_Generated at {report.generated_at.isoformat()} "
        f"in {report.investigation_duration_seconds:.2f}s_\n\n"
    )

    # TL;DR
    if report.llm_summary:
        w("## TL;DR\n\n")
        w(report.llm_summary.strip() + "\n\n")

    # Abstention banner
    if report.abstention:
        w("## ⚠️  Engine abstained\n\n")
        w(f"**{report.abstention.headline}**\n\n")
        w(report.abstention.detail.strip() + "\n\n")
        if report.abstention.diagnostics:
            w("Diagnostics:\n\n")
            for k, v in sorted(report.abstention.diagnostics.items()):
                w(f"- `{k}` = `{v}`\n")
            w("\n")

    # Environment quality (telemetry hygiene)
    if report.quality is not None:
        _render_quality(w, report.quality)

    # Cross-run context
    if report.history and report.history.occurrences_total >= 1:
        w("## Cross-run context\n\n")
        _render_history(w, report.history)

    # Flaky signal
    if report.flaky:
        w("## Flaky-test signal\n\n")
        cls = report.flaky.classification
        badge = {"flaky": "🎲", "genuine": "✅", "unknown": "❔"}.get(cls, "❔")
        w(
            f"{badge} **{cls}** — {report.flaky.note} "
            f"({report.flaky.fail_rate:.0%} fail rate over "
            f"{report.flaky.runs_considered} runs)\n\n"
        )

    # Failure block
    w("## Failure\n\n")
    w(f"- **Test:** `{report.failure.test_name}`\n")
    w(f"- **Environment:** `{report.failure.environment}`\n")
    w(f"- **When:** {report.failure.timestamp.isoformat()}\n")
    w(f"- **Trace:** `{report.failure.trace_id}`\n")
    if report.order_id:
        w(f"- **Order:** `{report.order_id}`\n")
    if report.related_trace_ids:
        w(f"- **Related traces:** {', '.join(f'`{t}`' for t in report.related_trace_ids)}\n")
    w(f"- **Assertion:** {report.failure.assertion}\n")
    if report.telemetry_counts:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(report.telemetry_counts.items()))
        w(f"- **Telemetry:** {counts}\n")
    w("\n")
    if report.failure.error_message:
        w("```\n")
        w(_strip_ansi(report.failure.error_message).strip() + "\n")
        w("```\n\n")

    # Primary
    if report.primary_hypothesis:
        w("## Primary hypothesis\n\n")
        _render_hypothesis(w, report.primary_hypothesis)
    elif not report.abstention:
        w("## Primary hypothesis\n\n_No deterministic hypothesis matched the telemetry._\n\n")

    # Alternatives / candidates
    if report.alternative_hypotheses:
        heading = "Candidate findings" if report.abstention else "Alternative hypotheses"
        w(f"## {heading}\n\n")
        for h in report.alternative_hypotheses:
            _render_hypothesis(w, h)

    # Timeline
    w("## Request timeline\n\n")
    if report.timeline_summary.strip():
        w("```\n")
        w(report.timeline_summary.rstrip() + "\n")
        w("```\n\n")
    else:
        w("_No timeline items._\n\n")

    # Evidence index
    if report.evidence_links:
        w("## Evidence index\n\n")
        for link in report.evidence_links:
            w(f"- {link}\n")
        w("\n")

    return buf.getvalue()


def _render_quality(w, q) -> None:
    BAND_BADGE = {"high": "🟢", "medium": "🟡", "low": "🔴"}
    w(f"## Environment quality\n\n")
    w(
        f"{BAND_BADGE.get(q.confidence_band, '⚪')} **{q.confidence_band}-confidence "
        f"environment** · overall score **{q.score:.2f}**\n\n"
    )
    if q.is_low_confidence:
        w(
            f"> ⚠️  Telemetry quality is below the low-confidence ceiling "
            f"({q.score:.2f} < 0.50). The primary hypothesis (if any) may be "
            f"derived from incomplete signals. Improve telemetry hygiene before "
            f"acting on this report; see the findings below.\n\n"
        )
    if q.coverages:
        w("| Signal | Coverage | Note |\n")
        w("|--------|----------|------|\n")
        for c in q.coverages:
            if not c.is_applicable:
                ratio_str = "—"
            else:
                ratio_str = f"{c.satisfied}/{c.applicable} ({c.ratio:.0%})"
            w(f"| `{c.signal}` | {ratio_str} | {c.note} |\n")
        w("\n")
    if q.findings:
        w("**Findings:**\n\n")
        for f in q.findings:
            badge = {"critical": "🛑", "warn": "⚠️", "info": "ℹ️"}.get(f.severity, "·")
            w(f"- {badge} `{f.signal}`: {f.message}\n")
        w("\n")
    if q.rules_will_not_fire:
        w(
            f"**Rules that cannot fire on this telemetry:** "
            + ", ".join(f"`{r}`" for r in q.rules_will_not_fire)
            + "  (their required signals are absent — silent no-op, not a bug).\n\n"
        )


def _render_history(w, h: HistoryContext) -> None:
    parts = [
        f"This same root-cause shape has been seen **{h.occurrences_total}** time(s) "
        f"by ARIP",
    ]
    if h.occurrences_window:
        parts.append(
            f"({h.occurrences_window} of them in the last {h.window_days} days)"
        )
    parts.append(f". Fingerprint: `{h.fingerprint}`.")
    w(" ".join(parts) + "\n\n")
    if h.first_seen:
        w(f"- First observed: {h.first_seen.isoformat()}\n")
    if h.last_seen:
        w(f"- Most recent:    {h.last_seen.isoformat()}\n")
    if h.affected_tests and len(h.affected_tests) > 1:
        w(f"- Tests affected: {len(h.affected_tests)} (")
        w(", ".join(f"`{t}`" for t in h.affected_tests[:5]))
        if len(h.affected_tests) > 5:
            w(f", … +{len(h.affected_tests) - 5}")
        w(")\n")
    w("\n")


def _render_hypothesis(w, h: Hypothesis) -> None:
    w(f"### {h.title}\n\n")
    w(
        f"- **Severity:** {h.severity}  ·  **Confidence:** {h.confidence:.2f}"
        + (f"  ·  **Rule:** `{h.rule_id}`" if h.rule_id else "")
        + "\n\n"
    )
    w(h.description.strip() + "\n\n")
    if h.suggested_next_step:
        w(f"**Suggested next step:** {h.suggested_next_step}\n\n")
    if h.evidence:
        w("**Evidence:**\n\n")
        for ev in h.evidence:
            w("- " + _render_evidence(ev) + "\n")
        w("\n")


def _render_evidence(ev: Evidence) -> str:
    parts = [f"`{ev.kind}` — {ev.description}"]
    if ev.service:
        parts.append(f"in `{ev.service}`")
    if ev.trace_id:
        if ev.link:
            parts.append(f"[trace]({ev.link})")
        else:
            parts.append(f"trace `{ev.trace_id}`")
    if ev.snippet:
        parts.append(f"`{ev.snippet[:160]}`")
    return " · ".join(parts)


def timeline_summary_from_items(items, limit: int = 40) -> str:
    """Render the first ``limit`` timeline items as a compact text block."""
    lines: list[str] = []
    for i, item in enumerate(items[:limit]):
        ts = item.timestamp.strftime("%H:%M:%S.%f")[:-3]
        lines.append(f"{ts}  {item.kind:11s}  [{item.service:20s}]  {item.summary}")
    if len(items) > limit:
        lines.append(f"... ({len(items) - limit} more items truncated)")
    return "\n".join(lines)


_ANSI_RE = None


def _strip_ansi(s: str) -> str:
    global _ANSI_RE
    if _ANSI_RE is None:
        import re

        _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    return _ANSI_RE.sub("", s)
