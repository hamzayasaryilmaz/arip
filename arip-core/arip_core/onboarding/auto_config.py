"""Auto-detect a NormalizationConfig from sampled telemetry.

`arip init` reads a JSONL bundle file (the output of any operator-side
adapter) and writes a YAML config that *matches the operator's actual
data*. Replaces the prior workflow of "read 4 docs and write the YAML
by hand."

What we detect (and the heuristic that drives each):

  business_keys
    Attributes that look like business correlation identifiers:
      - name matches one of {*.id, *_id, *.uuid, *Id} (case-insensitive)
      - appears in ≥ 30% of spans across ≥ 2 services
      - value shape consistent (ID-like, not free-form text)

  expected_services_per_trace
    Distinct service_name values seen in the sample.

  expected_log_sources
    Distinct service_name values from log entries (if logs present).

  handler_operation_patterns
    Token prefixes appearing on root-or-near-root spans. Picks up
    "POST ", "GET ", "handle_", "/api/" patterns automatically.

Each value comes with a `# detected from N spans across M traces`
comment in the emitted YAML so the operator sees the basis for each
choice and can override with confidence.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..correlator.models import CorrelatedTelemetry

# Attribute name → identifier? Common conventions.
_ID_LIKE_NAME = re.compile(r"(?:^|[\._])(id|uuid|guid|key|ref|no)$", re.IGNORECASE)

# Value-shape: hex, UUID, ULID, integer, prefixed-ID (ORD-xxx, USR-xxx).
_ID_LIKE_VALUE = re.compile(
    r"^("
    r"[0-9a-fA-F\-]{8,}"  # hex / UUID / GUID
    r"|[A-Z]{2,5}-[A-Za-z0-9_\-]{4,}"  # ORD-xxx, USR-xxx
    r"|\d{4,}"  # long-ish integer
    r")$"
)

# Operation-name prefixes worth detecting as "this is a handler entry-point".
_KNOWN_HANDLER_PREFIXES = (
    "GET ",
    "POST ",
    "PUT ",
    "DELETE ",
    "PATCH ",
    "HEAD ",
    "OPTIONS ",
    "handle_",
)


@dataclass
class DetectedConfig:
    """Result of inspecting a bundle file. Render via render_yaml()."""

    services: list[str] = field(default_factory=list)
    log_sources: list[str] = field(default_factory=list)
    business_keys: list[tuple[str, str]] = field(default_factory=list)  # (attr_name, evidence_note)
    handler_patterns: list[tuple[str, int]] = field(default_factory=list)  # (pattern, hit_count)
    db_patterns: list[str] = field(default_factory=list)
    n_traces: int = 0
    n_spans: int = 0
    n_logs: int = 0
    notes: list[str] = field(default_factory=list)


def detect_config(samples: list[CorrelatedTelemetry]) -> DetectedConfig:
    """Inspect a list of CorrelatedTelemetry, return a DetectedConfig."""
    out = DetectedConfig()
    out.n_traces = len(samples)
    if not samples:
        out.notes.append("no traces in sample — cannot detect anything")
        return out

    all_spans = [s for ct in samples for s in ct.spans]
    all_logs = [l for ct in samples for l in ct.logs]
    out.n_spans = len(all_spans)
    out.n_logs = len(all_logs)

    if not all_spans:
        out.notes.append("sample contained 0 spans across all traces")
        return out

    # ── Services ──────────────────────────────────────────────────
    services = sorted({s.service_name for s in all_spans if s.service_name})
    out.services = services

    # ── Log sources ────────────────────────────────────────────────
    out.log_sources = sorted({l.service_name for l in all_logs if l.service_name})

    # ── Business keys ──────────────────────────────────────────────
    # For each attribute name, track:
    #   - how many spans carry it
    #   - which services carry it (set)
    #   - sample values (for shape check)
    attr_span_count: Counter[str] = Counter()
    attr_services: defaultdict[str, set[str]] = defaultdict(set)
    attr_value_sample: defaultdict[str, list[Any]] = defaultdict(list)
    for s in all_spans:
        for k, v in (s.attributes or {}).items():
            attr_span_count[k] += 1
            attr_services[k].add(s.service_name)
            if len(attr_value_sample[k]) < 20:
                attr_value_sample[k].append(v)

    total_spans = len(all_spans)
    candidates: list[tuple[float, str, str]] = []  # (score, name, evidence)
    for name, count in attr_span_count.items():
        # Filter on name shape: must look like an identifier.
        if not _ID_LIKE_NAME.search(name):
            continue
        if count / total_spans < 0.10:  # appear on ≥ 10% of spans
            continue
        services_with = attr_services[name]
        if len(services_with) < 2:
            continue
        # Value shape consistency
        samples_str = [str(v) for v in attr_value_sample[name] if v is not None]
        if not samples_str:
            continue
        id_like_frac = sum(1 for v in samples_str if _ID_LIKE_VALUE.match(v)) / len(samples_str)
        if id_like_frac < 0.7:
            continue
        score = id_like_frac * len(services_with) * (count / total_spans)
        evidence = (
            f"appears on {count}/{total_spans} spans "
            f"across {len(services_with)} service(s); "
            f"value shape {id_like_frac:.0%} ID-like"
        )
        candidates.append((score, name, evidence))

    candidates.sort(reverse=True)
    # Cap at 3 — too many is noise. Operator can add more later.
    out.business_keys = [(name, ev) for _, name, ev in candidates[:3]]

    # ── Handler operation patterns ────────────────────────────────
    # Find root-or-near-root spans (depth 0–2) — those are usually
    # the entry-point handlers. Bucket their operation names by
    # the most informative leading token.
    span_by_id = {s.span_id: s for s in all_spans}

    def _depth(s, cap=6) -> int:
        d = 0
        cur = s
        while cur.parent_span_id and d < cap:
            p = span_by_id.get(cur.parent_span_id)
            if not p:
                break
            cur = p
            d += 1
        return d

    near_root = [s for s in all_spans if _depth(s) <= 1]
    prefix_counts: Counter[str] = Counter()
    for s in near_root:
        op = s.operation_name or ""
        matched = False
        for p in _KNOWN_HANDLER_PREFIXES:
            if op.startswith(p):
                prefix_counts[p] += 1
                matched = True
                break
        if not matched and "_" in op:
            # Catch arbitrary `handle_x`-style — only if the underscore
            # prefix is itself common.
            tok = op.split("_", 1)[0] + "_"
            if len(tok) >= 3:
                prefix_counts[tok] += 1

    top_handlers = [(pat, n) for pat, n in prefix_counts.most_common(6) if n >= 2]
    out.handler_patterns = top_handlers

    # ── DB operation patterns ──────────────────────────────────────
    if any((s.operation_name or "").startswith("db.") for s in all_spans):
        out.db_patterns = ["db."]
    if any("SELECT " in (s.operation_name or "") for s in all_spans):
        out.db_patterns.append("SELECT ")
    if any("INSERT " in (s.operation_name or "") for s in all_spans):
        out.db_patterns.append("INSERT ")

    return out


def render_yaml(detected: DetectedConfig, *, environment_name: str = "production") -> str:
    """Render a DetectedConfig as a NormalizationConfig YAML string.

    Every value carries a comment with the detection evidence so the
    operator sees exactly why it was chosen and can override with
    confidence. Empty fields are listed but commented out so the
    operator notices what wasn't detectable.
    """
    lines: list[str] = []
    add = lines.append

    add(
        f"# Auto-generated by `arip init` from a sample of "
        f"{detected.n_traces} trace(s), {detected.n_spans} spans, {detected.n_logs} logs."
    )
    add("# Review and edit before committing. Anything ARIP couldn't")
    add("# detect is listed as a commented-out stub.")
    add("")
    add(f"name: {environment_name}")
    add("")

    # Business keys
    add("# Business keys: cross-service correlation identifiers used by")
    add("# the concurrent_modification rule, business-key hygiene, and")
    add("# cross-trace lookup.")
    if detected.business_keys:
        add("business_keys:")
        for name, ev in detected.business_keys:
            add(f"  - {name}  # {ev}")
    else:
        add("# business_keys: []  # none detected — your services may not")
        add("#                    # tag spans with `order.id`-style attributes,")
        add("#                    # or all candidates appeared on <10% of spans")
    add("")

    # Expected services per trace
    add("# expected_services_per_trace: hygiene assertion — every trace")
    add("# is expected to touch each of these services. Mismatches surface")
    add("# in the digest's hygiene-findings section.")
    if detected.services:
        add("expected_services_per_trace:")
        for svc in detected.services:
            add(f"  - {svc}")
    else:
        add("# expected_services_per_trace: []  # no service names seen")
    add("")

    # Expected log sources
    add("# expected_log_sources: hygiene assertion — these services are")
    add("# expected to emit logs that join into trace bundles.")
    if detected.log_sources:
        add("expected_log_sources:")
        for svc in detected.log_sources:
            add(f"  - {svc}")
    else:
        add("# expected_log_sources: []  # no logs in sample — your bundle")
        add("#                           # was traces-only or logs weren't joined")
    add("")

    # Handler operation patterns
    add("# handler_operation_patterns: substrings used to recognise entry-")
    add("# point handlers (driving latency_vs_db). Defaults already cover")
    add("# HTTP-verb auto-instrumented frameworks; override if your")
    add("# services name handlers differently.")
    if detected.handler_patterns:
        add("handler_operation_patterns:")
        for pat, n in detected.handler_patterns:
            add(f'  - "{pat}"  # seen {n} time(s) as near-root span prefix')
    else:
        add("# handler_operation_patterns:  # defaults will be used")
        add('#   - "handle_"')
        add('#   - "POST "')
    add("")

    # DB patterns
    add("# db: operation-name substrings that mark DB spans. The")
    add("# latency_vs_db rule treats matching child spans as DB work.")
    add("db:")
    if detected.db_patterns:
        add("  operation_patterns:")
        for p in detected.db_patterns:
            add(f'    - "{p}"')
    else:
        add("  # operation_patterns:")
        add('  #   - "db."  # default — uncomment + adapt if your DB')
        add("  #            # spans use different naming")
    add("")

    if detected.notes:
        add("# Notes from detection:")
        for n in detected.notes:
            add(f"#   - {n}")

    return "\n".join(lines) + "\n"


def write_yaml(
    detected: DetectedConfig, out_path: Path, *, environment_name: str = "production"
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_yaml(detected, environment_name=environment_name))
