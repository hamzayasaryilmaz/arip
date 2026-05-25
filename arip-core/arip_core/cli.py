"""ARIP CLI.

Subcommands:
  arip investigate <report.json>     end-to-end investigation
  arip pr-comment <reports/dir>      render a concise PR comment from
                                     a directory of reports
  arip preflight <report.json>       onboarding diagnostic
  arip observe <source>              observation mode (Phase A) —
                                     incremental, read-only telemetry
                                     observation. No candidate tests,
                                     no PRs, no auto-anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from .canonical.config import NormalizationConfig, load_config_yaml
from .collector.failure_event import FailureEvent
from .collector.playwright_listener import parse_report, parse_test_runs
from .correlator.docker_logs_client import DockerLogsClient
from .correlator.jaeger_client import JaegerClient
from .correlator.models import CorrelatedTelemetry
from .correlator.timeline_builder import TimelineBuilder
from .engine.hypothesis import InvestigationResult, investigate
from .engine.models import Hypothesis
from .memory.fingerprint import fingerprint_hypothesis
from .memory.flaky import FlakyClassifier
from .memory.store import MemoryStore
from .quality.assessment import assess as assess_quality
from .reporter.llm_summarizer import summarize
from .reporter.markdown_writer import render, timeline_summary_from_items
from .reporter.models import FlakySignal, InvestigationReport

console = Console()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arip", description="Autonomous Reliability Investigation Platform")
    sub = parser.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("investigate", help="Investigate failures in a Playwright report")
    inv.add_argument("report", type=Path, help="Path to playwright-report.json")
    inv.add_argument("--out", type=Path, default=Path("reports"), help="Output directory (default: reports/)")
    inv.add_argument("--memory", type=Path, default=Path(".arip/memory.db"), help="SQLite memory store path")
    inv.add_argument("--environment", default="demo", help="Environment label")
    inv.add_argument("--jaeger", default="http://localhost:16686", help="Jaeger base URL")
    inv.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a normalization config YAML. If omitted, the built-in "
             "demo conventions are used.",
    )
    inv.add_argument("--no-llm", action="store_true", help="Skip LLM summarisation even if API key is set")
    inv.add_argument("--no-memory", action="store_true", help="Do not read or write the memory store")
    inv.add_argument("-v", "--verbose", action="store_true")

    pr = sub.add_parser("pr-comment", help="Render a concise PR comment from reports/")
    pr.add_argument("reports_dir", type=Path)
    pr.add_argument("-o", "--out", type=Path, default=None, help="Write to file (default: stdout)")
    pr.add_argument("--max-bytes", type=int, default=60_000, help="GitHub comment soft limit (default: 60000)")

    obs = sub.add_parser(
        "observe",
        help=(
            "Observation mode (Phase A): pull bounded slices of telemetry "
            "from a JSONL or directory source, run them through the "
            "deterministic engine, persist clusters. Read-only. "
            "No candidate tests, no PRs, no replay."
        ),
    )
    obs.add_argument(
        "source",
        help=(
            "Source URI. Supported: jsonl://path/to/file.jsonl[.gz] "
            "(byte-offset cursor), dir://path/to/dir (filename cursor). "
            "Bare paths are auto-detected (file → jsonl; directory → dir)."
        ),
    )
    obs.add_argument(
        "--store",
        type=Path,
        default=Path(".arip/observation.db"),
        help="SQLite path for observation state (default: .arip/observation.db)",
    )
    obs.add_argument(
        "--budget",
        type=int,
        default=500,
        help="Max observations per run (default: 500). Bounded memory.",
    )
    obs.add_argument(
        "--window",
        default=None,
        help=(
            "Display window for the digest, e.g. '7d', '24h'. "
            "Filters which clusters are shown by last_seen. "
            "Does NOT change ingestion; ingestion is always cursor-based."
        ),
    )
    obs.add_argument(
        "--min-recurrence",
        type=int,
        default=1,
        help="Minimum recurrence_count to include in the digest (default: 1).",
    )
    obs.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Normalization config YAML",
    )
    obs.add_argument(
        "--digest-out",
        type=Path,
        default=None,
        help="Write digest markdown to this path (default: stdout)",
    )
    obs.add_argument(
        "--no-ingest",
        action="store_true",
        help="Skip ingestion; just rebuild and print the digest from existing state.",
    )
    obs.add_argument("-v", "--verbose", action="store_true")

    pf = sub.add_parser(
        "preflight",
        help=(
            "Onboarding diagnostic: pick a sample failing trace from a "
            "Playwright report, run a quality assessment, and print which "
            "rules would fire vs which signals are missing."
        ),
    )
    pf.add_argument("report", type=Path, help="Path to playwright-report.json")
    pf.add_argument("--jaeger", default="http://localhost:16686", help="Jaeger base URL")
    pf.add_argument("--config", type=Path, default=None, help="Normalization config YAML")
    pf.add_argument("--environment", default="preflight")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "investigate":
        return _cmd_investigate(args)
    if args.cmd == "pr-comment":
        return _cmd_pr_comment(args)
    if args.cmd == "preflight":
        return _cmd_preflight(args)
    if args.cmd == "observe":
        return _cmd_observe(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


# ----- investigate ---------------------------------------------------


def _cmd_investigate(args) -> int:
    events = parse_report(args.report, environment=args.environment)
    runs = parse_test_runs(args.report, environment=args.environment)

    args.out.mkdir(parents=True, exist_ok=True)

    memory: MemoryStore | None = None
    flaky_classifier = FlakyClassifier()
    if not args.no_memory:
        memory = MemoryStore(args.memory)
        memory.record_test_runs_bulk(
            [
                (r.test_name, r.status, r.timestamp, r.environment, r.trace_id)
                for r in runs
            ]
        )

    if not events:
        console.print("[green]No failures in report.[/green]")
        return 0

    console.print(
        f"[bold]ARIP[/bold] investigating [cyan]{len(events)}[/cyan] failure(s) "
        f"({len(runs)} total test runs)"
    )

    table = Table(title="Investigation summary")
    table.add_column("Test", style="cyan", overflow="fold")
    table.add_column("Outcome", style="magenta", overflow="fold")
    table.add_column("Sev", justify="center")
    table.add_column("Conf", justify="right")
    table.add_column("Flaky", justify="center")
    table.add_column("Repeats", justify="right")
    table.add_column("Report", style="green", overflow="fold")

    if args.config is not None:
        config = load_config_yaml(args.config)
        console.print(f"[bold]Normalization config:[/bold] {args.config} (name: {config.name})")
    else:
        config = NormalizationConfig()

    with JaegerClient(base_url=args.jaeger) as jaeger:
        logs = DockerLogsClient()
        builder = TimelineBuilder(jaeger, logs, config=config)
        for ev in events:
            report, paths = _investigate_one(
                ev=ev,
                builder=builder,
                out_dir=args.out,
                use_llm=not args.no_llm,
                memory=memory,
                flaky=flaky_classifier,
            )
            if report.abstention:
                outcome = f"abstain — {report.abstention.headline}"
                sev = "—"
                conf = "—"
            elif report.primary_hypothesis:
                outcome = report.primary_hypothesis.title
                sev = report.primary_hypothesis.severity
                conf = f"{report.primary_hypothesis.confidence:.2f}"
            else:
                outcome = "—"
                sev = "—"
                conf = "—"
            flaky_cell = (
                report.flaky.classification if report.flaky else "—"
            )
            repeats_cell = (
                str(report.history.occurrences_total) if report.history else "—"
            )
            md_path = paths["markdown"]
            table.add_row(
                ev.test_name,
                outcome,
                sev,
                conf,
                flaky_cell,
                repeats_cell,
                str(md_path.relative_to(Path.cwd())) if md_path.is_relative_to(Path.cwd()) else str(md_path),
            )

    console.print()
    console.print(table)
    return 0


def _investigate_one(
    *,
    ev: FailureEvent,
    builder: TimelineBuilder,
    out_dir: Path,
    use_llm: bool,
    memory: MemoryStore | None,
    flaky: FlakyClassifier,
) -> tuple[InvestigationReport, dict[str, Path]]:
    started = time.monotonic()
    ct = builder.build(ev)
    result: InvestigationResult = investigate(ct)

    timeline_text = timeline_summary_from_items(ct.timeline)
    evidence_links = sorted({e.link for h in result.all_ranked for e in h.evidence if e.link})

    duration = time.monotonic() - started

    report = InvestigationReport(
        failure=ev,
        primary_hypothesis=result.primary,
        alternative_hypotheses=result.alternatives,
        timeline_summary=timeline_text,
        evidence_links=evidence_links,
        generated_at=datetime.now(tz=timezone.utc),
        investigation_duration_seconds=duration,
        primary_trace_id=ct.primary_trace_id,
        related_trace_ids=ct.related_trace_ids,
        order_id=ct.order_id,
        abstention=result.abstention,
        telemetry_counts={
            "spans": len(ct.spans),
            "logs": len(ct.logs),
            "db_queries": len(ct.db_queries),
            "timeline_items": len(ct.timeline),
        },
        quality=assess_quality(ct),
    )

    fingerprint: str | None = None
    if result.primary is not None:
        fingerprint = fingerprint_hypothesis(result.primary)

    if memory is not None:
        if fingerprint:
            report.history = memory.history_for_fingerprint(fingerprint)
        considered, fails = memory.test_run_stats(ev.test_name)
        verdict = flaky.classify(considered, fails)
        report.flaky = FlakySignal(
            test_name=ev.test_name,
            runs_considered=verdict.runs_considered,
            fail_rate=verdict.fail_rate,
            classification=verdict.classification,
            note=verdict.note,
        )

    if use_llm:
        try:
            report.llm_summary = summarize(report)
        except Exception:
            logging.exception("LLM summarisation failed")

    slug = _slugify(ev.test_name) + "-" + ev.trace_id[:8]
    md_path = out_dir / f"{slug}.md"
    json_path = out_dir / f"{slug}.json"
    md_path.write_text(render(report))
    json_path.write_text(json.dumps(_report_to_dict(report, ct), indent=2, sort_keys=True, default=str))

    if memory is not None:
        memory.record_investigation(report, fingerprint=fingerprint, report_path=str(md_path))

    return report, {"markdown": md_path, "json": json_path}


def _slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "_"}:
            out.append("-")
    return "".join(out).strip("-")[:60] or "report"


def _report_to_dict(report: InvestigationReport, ct: CorrelatedTelemetry) -> dict[str, Any]:
    return {
        "failure": report.failure.to_dict(),
        "primary_hypothesis": _hypothesis_dict(report.primary_hypothesis),
        "alternative_hypotheses": [_hypothesis_dict(h) for h in report.alternative_hypotheses],
        "abstention": asdict(report.abstention) if report.abstention else None,
        "history": asdict(report.history) if report.history else None,
        "flaky": asdict(report.flaky) if report.flaky else None,
        "quality": asdict(report.quality) if report.quality else None,
        "primary_trace_id": report.primary_trace_id,
        "related_trace_ids": report.related_trace_ids,
        "order_id": report.order_id,
        "evidence_links": report.evidence_links,
        "llm_summary": report.llm_summary,
        "generated_at": report.generated_at.isoformat(),
        "investigation_duration_seconds": report.investigation_duration_seconds,
        "telemetry_counts": report.telemetry_counts,
    }


def _hypothesis_dict(h: Hypothesis | None) -> dict[str, Any] | None:
    if h is None:
        return None
    return asdict(h)


# ----- pr-comment ----------------------------------------------------


def _cmd_pr_comment(args) -> int:
    from .integrations.github import render_pr_comment

    reports_dir: Path = args.reports_dir
    json_files = sorted(reports_dir.glob("*.json"))
    if not json_files:
        msg = f"_ARIP found no investigation reports under `{reports_dir}`._"
        _emit_pr_comment(msg, args)
        return 0

    payloads = [json.loads(p.read_text()) for p in json_files]
    body = render_pr_comment(payloads, max_bytes=args.max_bytes)
    _emit_pr_comment(body, args)
    return 0


def _emit_pr_comment(body: str, args) -> None:
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body)
    else:
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")


# ----- preflight ------------------------------------------------------


def _cmd_preflight(args) -> int:
    """Onboarding diagnostic: pick the first failure from a Playwright
    report, fetch its telemetry, and report quality + rule readiness.
    Does not run rules, does not write reports."""
    from .quality.contracts import RULE_CONTRACTS, contracts_for_rule

    events = parse_report(args.report, environment=args.environment)
    if not events:
        console.print("[yellow]no failures in report — nothing to preflight against[/yellow]")
        return 0

    if args.config is not None:
        config = load_config_yaml(args.config)
        console.print(f"Loaded config: [bold]{args.config}[/bold] (name: {config.name})")
    else:
        config = NormalizationConfig()
        console.print("Using built-in default config (demo conventions)")

    ev = events[0]
    console.print(f"Preflighting against failure: [cyan]{ev.test_name}[/cyan]")
    console.print(f"  trace_id={ev.trace_id}  environment={ev.environment}")

    with JaegerClient(base_url=args.jaeger) as jaeger:
        builder = TimelineBuilder(jaeger, DockerLogsClient(), config=config)
        ct = builder.build(ev)

    q = assess_quality(ct)

    band_colour = {"high": "green", "medium": "yellow", "low": "red"}
    console.print()
    console.print(
        f"Environment quality: [bold {band_colour.get(q.confidence_band, 'white')}]"
        f"{q.confidence_band}[/] · score [bold]{q.score:.2f}[/]"
    )
    console.print(f"  spans={len(ct.spans)}  logs={len(ct.logs)}  db_queries={len(ct.db_queries)}")

    if q.coverages:
        console.print()
        cov_table = Table(title="Signal coverage", show_header=True, header_style="bold")
        cov_table.add_column("Signal", style="cyan")
        cov_table.add_column("Coverage", justify="right")
        cov_table.add_column("Note", overflow="fold")
        for c in q.coverages:
            if not c.is_applicable:
                cov = "—"
            else:
                cov = f"{c.satisfied}/{c.applicable} ({c.ratio:.0%})"
            cov_table.add_row(c.signal, cov, c.note)
        console.print(cov_table)

    if q.findings:
        console.print()
        console.print("[bold]Findings:[/bold]")
        for f in q.findings:
            colour = {"critical": "red", "warn": "yellow", "info": "white"}[f.severity]
            console.print(f"  [{colour}]{f.severity:8s}[/] {f.signal:30s} {f.message}")

    console.print()
    console.print("[bold]Rule readiness[/bold] — would this telemetry let each rule fire?")
    for c in RULE_CONTRACTS:
        ready = c.rule_id in q.rules_likely_to_fire
        mark = "[green]✓[/]" if ready else "[red]✗[/]"
        console.print(f"  {mark} {c.rule_id:<26s}  {c.description}")
        if not ready:
            missing = ", ".join(c.required_signals)
            console.print(f"      [dim]→ missing required signal(s): {missing}[/]")

    if q.is_low_confidence:
        console.print()
        console.print(
            "[bold red]⚠️  This is a low-confidence environment.[/] "
            "Improving the gaps above will materially raise ARIP's "
            "ability to produce a primary hypothesis."
        )
    return 0


# ----- observe -------------------------------------------------------


def _cmd_observe(args) -> int:
    """Observation mode — Phase A. Read-only. Bounded. Resumable.

    No candidate tests. No PRs. No replay. No alerting. Just clusters."""
    from .observation.digest import build_digest, render_digest
    from .observation.pipeline import observe
    from .observation.sources import (
        DirectoryTraceSource,
        JsonlTraceSource,
    )
    from .observation.store import ObservationStore

    if args.config is not None:
        config = load_config_yaml(args.config)
        console.print(f"[bold]Normalization config:[/bold] {args.config} (name: {config.name})")
    else:
        config = NormalizationConfig()

    store = ObservationStore(args.store)

    window_days = _parse_window_days(args.window)
    window_label = args.window or ""

    summary = None
    if not args.no_ingest:
        source = _resolve_source(args.source)
        console.print(
            f"[bold]ARIP observe[/bold] · source [cyan]{source.name}[/cyan] · "
            f"budget [bold]{args.budget}[/bold]"
        )
        cursor_before = store.load_cursor(source.name)
        if cursor_before is None:
            console.print("  no prior cursor — starting from the beginning")
        else:
            console.print(f"  resuming from cursor [dim]{cursor_before}[/dim]")
        summary = observe(
            source=source,
            store=store,
            budget=args.budget,
            config=config,
            window_label=window_label,
        )
        console.print(
            f"  traces observed: [bold]{summary.traces_observed}[/bold] · "
            f"new events: [bold]{summary.events_new}[/bold] · "
            f"idempotent skips: [dim]{summary.events_skipped_idempotent}[/dim]"
        )

    digest = build_digest(
        store,
        window_days=window_days,
        window_label=window_label,
        min_recurrence=args.min_recurrence,
        summary=summary,
    )
    text = render_digest(digest)

    if args.digest_out is not None:
        args.digest_out.parent.mkdir(parents=True, exist_ok=True)
        args.digest_out.write_text(text)
        console.print(f"  digest written to [green]{args.digest_out}[/green]")
    else:
        console.print()
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _resolve_source(uri: str):
    """Resolve a CLI source string to a Source instance.

    Accepts:
      - jsonl://path  → JsonlTraceSource
      - dir://path    → DirectoryTraceSource
      - bare path     → auto-detect: .jsonl[.gz] / file → JSONL;
                        directory → DirectoryTraceSource
    """
    from .observation.sources import DirectoryTraceSource, JsonlTraceSource

    if uri.startswith("jsonl://"):
        return JsonlTraceSource(uri[len("jsonl://"):])
    if uri.startswith("dir://"):
        return DirectoryTraceSource(uri[len("dir://"):])
    p = Path(uri)
    if p.is_dir():
        return DirectoryTraceSource(p)
    if p.is_file():
        return JsonlTraceSource(p)
    raise SystemExit(f"could not resolve source: {uri}")


def _parse_window_days(window: str | None) -> int | None:
    """Parse '7d' / '24h' / '60m' to a day count. Returns None for None."""
    if not window:
        return None
    w = window.strip().lower()
    try:
        if w.endswith("d"):
            return max(1, int(w[:-1]))
        if w.endswith("h"):
            hours = int(w[:-1])
            return max(1, (hours + 23) // 24)
        if w.endswith("m"):
            minutes = int(w[:-1])
            return max(1, (minutes + 60 * 24 - 1) // (60 * 24))
        return max(1, int(w))
    except ValueError:
        return None


if __name__ == "__main__":
    sys.exit(main())
