"""Render an observation digest as markdown.

The digest is the operator-facing surface of Phase A. It is read, not
parsed. Keep it short, honest, and explicit about what is NOT here
(candidate tests, PRs, alerts).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from io import StringIO

from .models import AnomalyCluster, ObservationDigest, ObservationSummary
from .store import ObservationStore


def build_digest(
    store: ObservationStore,
    *,
    window_days: int | None = None,
    window_label: str = "",
    min_recurrence: int = 1,
    summary: ObservationSummary | None = None,
) -> ObservationDigest:
    rule_clusters = store.list_clusters(
        kind="rule",
        window_days=window_days,
        min_recurrence=min_recurrence,
    )
    abstention_clusters = store.list_clusters(
        kind="abstention",
        window_days=window_days,
        min_recurrence=min_recurrence,
    )
    low_q = store.count_low_quality_events(window_days=window_days)
    return ObservationDigest(
        generated_at=datetime.now(tz=UTC),
        window_label=window_label,
        summary=summary,
        rule_clusters=rule_clusters,
        abstention_clusters=abstention_clusters,
        low_quality_count=low_q,
        notes=(),
    )


def render_digest(digest: ObservationDigest) -> str:
    out = StringIO()
    out.write("# ARIP observation digest\n\n")
    out.write(
        f"_generated {digest.generated_at.isoformat()}"
        + (f" · window: {digest.window_label}" if digest.window_label else "")
        + "_\n\n"
    )

    if digest.summary is not None:
        _write_summary(out, digest.summary)
        # If the prerequisite gate fired, surface it prominently
        # BEFORE any (empty) recurring-patterns sections so the
        # operator immediately understands why nothing was produced.
        if digest.summary.prerequisite_failure is not None:
            pf = digest.summary.prerequisite_failure
            out.write("## ⚠️  Telemetry prerequisite failed — engine did NOT run\n\n")
            out.write(f"**{pf.headline}**\n\n")
            out.write(f"{pf.detail}\n\n")
            out.write(f"**Next step:** {pf.next_step}\n\n")
        # Hygiene findings — operator-facing telemetry-gap surface
        if digest.summary.hygiene_findings:
            out.write("## Telemetry-hygiene findings\n\n")
            out.write(
                "Specific gaps in this telemetry that would let more rules "
                "fire or strengthen the engine's existing decisions. ARIP "
                "doesn't make these up — each finding is grounded in what "
                "the bundle did or didn't contain.\n\n"
            )
            for finding in digest.summary.hygiene_findings:
                out.write(f"- {finding}\n")
            out.write("\n")

    out.write("## Recurring patterns (rule-grounded)\n\n")
    if not digest.rule_clusters:
        out.write("_No rule-grounded recurring patterns in this window._\n\n")
    else:
        _write_rule_table(out, digest.rule_clusters)

    out.write("## Recurring abstentions\n\n")
    out.write(
        "These telemetry shapes recurred, but the engine could not nominate "
        "a primary hypothesis. Useful for telemetry-hygiene work, not for "
        "acting on the anomaly itself.\n\n"
    )
    if not digest.abstention_clusters:
        out.write("_No abstention clusters in this window._\n\n")
    else:
        _write_abstention_table(out, digest.abstention_clusters)

    if digest.low_quality_count:
        out.write("## Low-quality observations\n\n")
        out.write(
            f"{digest.low_quality_count} observation(s) in this window had a "
            "quality band of `low`. They are recorded for transparency but "
            "are NOT considered reliable enough to be acted on as patterns. "
            "Improving the telemetry hygiene gaps listed in each "
            "investigation's quality findings will let more of these become "
            "reasoning material.\n\n"
        )

    out.write("## What this digest is NOT\n\n")
    out.write(
        "- Not a list of confirmed root causes — every cluster is an\n"
        "  evidence-aligned observation, not a verdict.\n"
        "- Not a reproduction-candidate list — no test draft has been\n"
        "  generated, no PR has been opened.\n"
        "- Not an alerting surface — recurrence counts are descriptive,\n"
        "  not thresholds for paging anyone.\n"
        "- Not exhaustive — observation mode runs against whatever sources\n"
        "  the operator pointed it at; absence here ≠ absence in reality.\n"
    )
    return out.getvalue()


def _write_summary(out: StringIO, s: ObservationSummary) -> None:
    out.write("## Run summary\n\n")
    out.write(f"- source: `{s.source_name}`\n")
    out.write(f"- traces observed: {s.traces_observed}\n")
    out.write(f"- new events: {s.events_new}\n")
    out.write(f"- idempotent skips: {s.events_skipped_idempotent}\n")
    if s.cursor_before is not None or s.cursor_after is not None:
        out.write(f"- cursor: `{s.cursor_before or '∅'}` → `{s.cursor_after or '∅'}`\n")
    if s.quality_band_counts:
        bands = ", ".join(f"{b}={n}" for b, n in sorted(s.quality_band_counts.items()))
        out.write(f"- quality band distribution: {bands}\n")
    if s.rule_match_counts:
        rules = ", ".join(f"{r}={n}" for r, n in sorted(s.rule_match_counts.items()))
        out.write(f"- rule matches: {rules}\n")
    if s.abstention_code_counts:
        ab = ", ".join(f"{c}={n}" for c, n in sorted(s.abstention_code_counts.items()))
        out.write(f"- abstentions: {ab}\n")
    out.write("\n")


def _write_rule_table(out: StringIO, clusters: Sequence[AnomalyCluster]) -> None:
    out.write(
        "| rule | recurrence | first seen | last seen | quality | services | operations |\n"
        "|---|---:|---|---|---|---|---|\n"
    )
    for c in clusters:
        out.write(
            f"| `{c.rule_id}` | {c.recurrence_count} "
            f"| {_short_dt(c.first_seen)} | {_short_dt(c.last_seen)} "
            f"| {c.dominant_quality_band} "
            f"| {_join(c.service_set)} "
            f"| {_join(c.operation_names_sample, 4)} |\n"
        )
    out.write("\n")


def _write_abstention_table(out: StringIO, clusters: Sequence[AnomalyCluster]) -> None:
    out.write(
        "| abstention | recurrence | first seen | last seen | services | operations |\n"
        "|---|---:|---|---|---|---|\n"
    )
    for c in clusters:
        out.write(
            f"| `{c.abstention_code}` | {c.recurrence_count} "
            f"| {_short_dt(c.first_seen)} | {_short_dt(c.last_seen)} "
            f"| {_join(c.service_set)} "
            f"| {_join(c.operation_names_sample, 4)} |\n"
        )
    out.write("\n")


def _join(items: Sequence[str], limit: int = 6) -> str:
    if not items:
        return "—"
    truncated = list(items)[:limit]
    extra = len(items) - len(truncated)
    s = ", ".join(truncated)
    if extra > 0:
        s += f" (+{extra})"
    return s


def _short_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
