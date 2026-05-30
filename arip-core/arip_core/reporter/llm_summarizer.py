"""Optional natural-language summarisation of an investigation report.

Strict scope: the LLM **only** produces a 2-4 sentence TL;DR from the
already-deterministic findings. Core analysis is never delegated to it.
If no API key is configured, we fall back to a deterministic summary so
that the rest of the pipeline keeps working offline.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import InvestigationReport

log = logging.getLogger(__name__)

_MODEL = "claude-opus-4-7"


def summarize(report: InvestigationReport) -> str:
    """Return a short summary. Uses Claude when ``ANTHROPIC_API_KEY`` is
    set; otherwise returns a deterministic fallback derived from the
    primary hypothesis."""
    if not report.primary_hypothesis:
        return "No primary hypothesis could be derived from the available telemetry."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _deterministic_summary(report)

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed; using deterministic summary")
        return _deterministic_summary(report)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(report)
    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system=(
                "You paraphrase a deterministic investigation finding into a "
                "tight, evidence-grounded summary. Rules: 2-4 sentences. "
                "Hedge appropriately — the input is a hypothesis with a "
                "confidence score, not a proven root cause; use words like "
                "'most likely', 'the strongest signal points at', 'evidence "
                "suggests'. Never claim certainty the input does not claim. "
                "No new claims beyond the supplied findings. No marketing "
                "language. Plain English. Lead with the primary hypothesis, "
                "then what the evidence shows, then the suggested next step."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return text or _deterministic_summary(report)
    except Exception:
        log.exception("LLM summarisation failed; falling back")
        return _deterministic_summary(report)


def _deterministic_summary(report: InvestigationReport) -> str:
    h = report.primary_hypothesis
    assert h is not None
    lines = [f"{h.title}. {h.description.splitlines()[0]}"]
    if h.suggested_next_step:
        lines.append(f"Next step: {h.suggested_next_step}")
    return " ".join(lines)


def _build_prompt(report: InvestigationReport) -> str:
    h = report.primary_hypothesis
    assert h is not None
    parts = [
        f"Failure: {report.failure.test_name}",
        f"Assertion: {report.failure.assertion}",
        f"Primary hypothesis: {h.title} (severity={h.severity}, confidence={h.confidence:.2f})",
        h.description,
        "",
        "Evidence:",
    ]
    for ev in h.evidence[:6]:
        parts.append(f"- [{ev.kind}] {ev.description}")
    if h.suggested_next_step:
        parts += ["", f"Suggested next step: {h.suggested_next_step}"]
    if report.alternative_hypotheses:
        parts += ["", "Alternative findings:"]
        for alt in report.alternative_hypotheses[:3]:
            parts.append(f"- {alt.title} ({alt.severity}, conf {alt.confidence:.2f})")
    return "\n".join(parts)
