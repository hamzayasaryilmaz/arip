"""Render a concise PR comment from a directory of investigation reports.

GitHub silently truncates comments above ~64 KB. The renderer:

  * Surfaces only what an engineer scans first (test name, top finding,
    confidence, flaky/cross-run signal, jaeger link).
  * Folds full descriptions into ``<details>`` blocks so the comment
    stays scannable.
  * Aborts gracefully when it would exceed the byte budget, listing
    the rest by title with a link to the artifact bundle.
"""

from __future__ import annotations

from io import StringIO
from typing import Any


HEADER = "## 🔬 ARIP investigation\n\n"
MAX_TABLE_ROWS = 25


def render_pr_comment(reports: list[dict[str, Any]], max_bytes: int = 60_000) -> str:
    """Render PR comment markdown.

    ``reports`` is a list of dicts as produced by ``cli._report_to_dict``.
    Caps both the summary table and the per-report details to stay under
    ``max_bytes`` (GitHub's PR comment soft limit is ~64 KB).
    """
    if not reports:
        return HEADER + "_No failures investigated._\n"

    failures = len(reports)
    abstained = sum(1 for r in reports if r.get("abstention"))
    flagged_flaky = sum(
        1 for r in reports if (r.get("flaky") or {}).get("classification") == "flaky"
    )
    low_q = sum(
        1 for r in reports
        if (r.get("quality") or {}).get("confidence_band") == "low"
    )

    buf = StringIO()
    buf.write(HEADER)
    buf.write(f"**{failures}** failure(s) investigated")
    bits: list[str] = []
    if abstained:
        bits.append(f"{abstained} abstained (insufficient telemetry)")
    if flagged_flaky:
        bits.append(f"{flagged_flaky} flagged as flaky")
    if low_q:
        bits.append(f"{low_q} in low-confidence environment")
    if bits:
        buf.write(" · " + " · ".join(bits))
    buf.write("\n\n")

    # Table summary (capped)
    table_rows = reports[:MAX_TABLE_ROWS]
    buf.write("| Test | Finding | Sev | Conf | Flaky | Repeats |\n")
    buf.write("|------|---------|-----|------|-------|---------|\n")
    for r in table_rows:
        test_name = _truncate(r["failure"]["test_name"], 60)
        primary = r.get("primary_hypothesis")
        abst = r.get("abstention")
        if primary:
            finding = _truncate(primary["title"], 60)
            sev = primary.get("severity", "—")
            conf = f"{primary.get('confidence', 0):.2f}"
        elif abst:
            finding = f"_{_truncate(abst['headline'], 60)}_"
            sev = "—"
            conf = "—"
        else:
            finding = "—"
            sev = "—"
            conf = "—"
        flaky = r.get("flaky") or {}
        flaky_cell = flaky.get("classification", "—") if flaky else "—"
        hist = r.get("history") or {}
        repeats = str(hist.get("occurrences_total", "—")) if hist else "—"
        buf.write(f"| {test_name} | {finding} | {sev} | {conf} | {flaky_cell} | {repeats} |\n")
    if len(reports) > MAX_TABLE_ROWS:
        buf.write(f"| _… and {len(reports) - MAX_TABLE_ROWS} more_ | | | | | |\n")
    buf.write("\n")

    # Per-report detail block, also constrained
    closing_note = (
        "_…{n} more report(s) omitted from this comment to stay under "
        "the PR comment size limit. See the workflow artifacts for "
        "the full set._\n"
    )
    note_overhead = len(closing_note.format(n=failures))

    for i, r in enumerate(reports, start=1):
        section = _render_one(r, idx=i)
        if buf.tell() + len(section) + note_overhead > max_bytes:
            remaining = failures - (i - 1)
            buf.write(closing_note.format(n=remaining))
            break
        buf.write(section)

    return buf.getvalue()


def _render_one(r: dict[str, Any], *, idx: int) -> str:
    buf = StringIO()
    test = r["failure"]["test_name"]
    primary = r.get("primary_hypothesis")
    abst = r.get("abstention")
    history = r.get("history") or {}
    flaky = r.get("flaky") or {}

    buf.write(f"<details>\n<summary><strong>{idx}. {_md_escape(test)}</strong></summary>\n\n")

    if abst:
        buf.write(f"> ⚠️ **Engine abstained.** {abst['headline']}\n\n")
        buf.write(abst["detail"].strip() + "\n\n")
    elif primary:
        buf.write(
            f"**{primary['title']}** "
            f"(severity `{primary.get('severity', '?')}`, "
            f"confidence `{primary.get('confidence', 0):.2f}`, "
            f"rule `{primary.get('rule_id', '?')}`)\n\n"
        )
        buf.write(_truncate(primary["description"].strip(), 600) + "\n\n")
        if primary.get("suggested_next_step"):
            buf.write(f"**Next step:** {primary['suggested_next_step']}\n\n")

    # cross-run + flaky
    nuggets: list[str] = []
    if history.get("occurrences_total", 0) >= 1:
        nuggets.append(
            f"Seen **{history['occurrences_total']}** time(s) before "
            f"({history.get('occurrences_window', 0)} in the last "
            f"{history.get('window_days', '?')} days). Fingerprint "
            f"`{history.get('fingerprint', '?')}`."
        )
    if flaky.get("classification") == "flaky":
        nuggets.append(
            f"🎲 **Flaky test** — {flaky.get('fail_rate', 0):.0%} fail rate "
            f"over {flaky.get('runs_considered', 0)} recent runs."
        )
    elif flaky.get("classification") == "genuine" and flaky.get("runs_considered", 0) > 0:
        nuggets.append(
            f"✅ Stable test history "
            f"({flaky.get('fail_rate', 0):.0%} fail rate over "
            f"{flaky.get('runs_considered', 0)} runs)."
        )
    for n in nuggets:
        buf.write(f"- {n}\n")
    if nuggets:
        buf.write("\n")

    # evidence (compact)
    if primary and primary.get("evidence"):
        buf.write("**Evidence:**\n\n")
        for ev in primary["evidence"][:5]:
            line = f"- `{ev.get('kind', '?')}` — {_truncate(ev.get('description', ''), 180)}"
            if ev.get("link"):
                line += f" — [trace]({ev['link']})"
            buf.write(line + "\n")
        if len(primary["evidence"]) > 5:
            buf.write(f"- _… {len(primary['evidence']) - 5} more_\n")
        buf.write("\n")

    buf.write("</details>\n\n")
    return buf.getvalue()


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")
