"""Stress tests for Phase A observation behaviour.

Validation focus: does observation mode stay deterministic, readable,
bounded, and trustworthy under production-style noisy telemetry?

These tests do NOT add new capability. They exercise the existing
pipeline against messy fixtures and assert the invariants we want to
hold in the wild.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arip_core.observation.digest import build_digest, render_digest
from arip_core.observation.pipeline import observe
from arip_core.observation.sources import JsonlTraceSource
from arip_core.observation.store import ObservationStore

from .fixtures.synthetic_telemetry import (
    BASE,
    burst_outage_traces,
    cascading_failure_traces,
    downstream_error_trace,
    healthy_trace,
    mixed_noise_traces,
    orphan_span_trace,
    pool_exhaustion_trace,
    retry_storm_trace,
    write_jsonl,
    write_truncated_jsonl,
)


# ---------- 1. Burst outage cluster stability ----------------------


def test_burst_outage_collapses_to_one_rule_cluster(tmp_path: Path) -> None:
    """200 traces of the same retry_storm shape → exactly one rule cluster
    with recurrence_count ≈ 200. Cluster explosion is the failure mode
    here; we are guarding against it."""
    jsonl = tmp_path / "burst.jsonl"
    bundles = burst_outage_traces(n=200)
    write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "obs.db")
    summary = observe(source=JsonlTraceSource(jsonl), store=store, budget=500)
    assert summary.events_new == 200

    rule_clusters = store.list_clusters(kind="rule")
    abstention_clusters = store.list_clusters(kind="abstention")
    total_recurrence = sum(c.recurrence_count for c in rule_clusters) + sum(
        c.recurrence_count for c in abstention_clusters
    )
    assert total_recurrence == 200
    # The retry_storm fingerprint is service-set + evidence-kinds based;
    # attempt-count variation must not split the cluster.
    rule_fps = {c.fingerprint for c in rule_clusters}
    assert len(rule_fps) <= 1, (
        f"burst outage should collapse to ≤ 1 rule cluster; got "
        f"{len(rule_fps)} fingerprints"
    )


# ---------- 2. Mixed scenarios cluster correctly --------------------


def test_cascading_failure_produces_distinct_rule_clusters(tmp_path: Path) -> None:
    """A real outage is rarely one shape. We expect ≤ 3 rule clusters
    (one per distinct rule that fires), not 50 (one per trace)."""
    jsonl = tmp_path / "cascading.jsonl"
    write_jsonl(jsonl, cascading_failure_traces(n=50))
    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=200)

    rule_clusters = store.list_clusters(kind="rule")
    rule_ids = {c.rule_id for c in rule_clusters}
    # Bound: at most 5 (the total number of shipped rules). Realistic
    # expectation: 2-3 distinct rules participate.
    assert len(rule_clusters) <= 5
    assert rule_ids <= {
        "concurrent_modification",
        "retry_storm",
        "downstream_error",
        "db_pool_exhaustion",
        "latency_vs_db",
    }
    # And the cluster recurrence sums match the input count.
    abstention_clusters = store.list_clusters(kind="abstention")
    total = sum(c.recurrence_count for c in rule_clusters) + sum(
        c.recurrence_count for c in abstention_clusters
    )
    assert total == 50


# ---------- 3. Partial / orphan traces stay in abstention bucket ----


def test_orphan_spans_do_not_pollute_rule_clusters(tmp_path: Path) -> None:
    """Orphan-span traces should land in abstention buckets (or no_rule_matched
    for one-span healthy traces), NOT in rule-grounded clusters."""
    jsonl = tmp_path / "orphans.jsonl"
    bundles = [orphan_span_trace(f"orph-{i}") for i in range(10)]
    write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=50)

    rule_clusters = store.list_clusters(kind="rule")
    abstention_clusters = store.list_clusters(kind="abstention")
    # No rule cluster — engine should not nominate a primary on this shape.
    assert rule_clusters == []
    # And the abstention code is one of the canonical five.
    codes = {c.abstention_code for c in abstention_clusters}
    assert codes <= {
        "no_primary_trace",
        "empty_telemetry",
        "no_rule_matched",
        "weak_evidence",
        "conflicting_hypotheses",
    }


# ---------- 4. Cursor robustness: truncated JSONL -------------------


def test_truncated_jsonl_does_not_crash_or_loop(tmp_path: Path) -> None:
    """A writer that died mid-flush leaves a half-line. The source must
    advance the cursor past valid lines and not hang on the truncated
    tail."""
    jsonl = tmp_path / "truncated.jsonl"
    bundles = burst_outage_traces(n=10)
    write_truncated_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "obs.db")
    s1 = observe(source=JsonlTraceSource(jsonl), store=store, budget=100)
    # All 10 valid lines should be processed.
    assert s1.events_new == 10
    # Cursor advanced; second run is a no-op (still no valid new line).
    s2 = observe(source=JsonlTraceSource(jsonl), store=store, budget=100)
    assert s2.traces_observed == 0
    assert s2.events_new == 0


# ---------- 5. Crash-recovery via cursor ----------------------------


def test_cursor_resumes_after_simulated_crash(tmp_path: Path) -> None:
    """Mid-stream crash → next process resumes from cursor → exactly-once
    semantics over the source."""
    jsonl = tmp_path / "long.jsonl"
    write_jsonl(jsonl, burst_outage_traces(n=20))

    store = ObservationStore(tmp_path / "obs.db")
    # First run: process only 7, simulating a crash via budget.
    s1 = observe(source=JsonlTraceSource(jsonl), store=store, budget=7)
    assert s1.events_new == 7
    # "Restart" with the same store: cursor picks up where we left off.
    s2 = observe(source=JsonlTraceSource(jsonl), store=store, budget=100)
    assert s2.events_new == 13
    # Total recurrence equals input.
    total = sum(c.recurrence_count for c in store.list_clusters(kind="rule"))
    assert total == 20


# ---------- 6. Idempotency under re-ingestion -----------------------


def test_idempotent_under_replay(tmp_path: Path) -> None:
    """Forcibly replay the same file from cursor 0. Events must be
    skipped, not double-counted."""
    jsonl = tmp_path / "replay.jsonl"
    write_jsonl(jsonl, burst_outage_traces(n=30))

    store = ObservationStore(tmp_path / "obs.db")
    source = JsonlTraceSource(jsonl)
    s1 = observe(source=source, store=store, budget=100)
    assert s1.events_new == 30

    store.save_cursor(source.name, "0")
    s2 = observe(source=source, store=store, budget=100)
    assert s2.events_new == 0
    assert s2.events_skipped_idempotent == 30
    # Cluster recurrence unchanged.
    total = sum(c.recurrence_count for c in store.list_clusters(kind="rule"))
    assert total == 30


# ---------- 7. Gzip rotation handling -------------------------------


def test_gzipped_archive_processes_same_as_plain(tmp_path: Path) -> None:
    """Rotated logs typically become .gz archives. Processing a gzipped
    archive must produce the same event count as processing the plain
    file would."""
    plain = tmp_path / "plain.jsonl"
    bundles = burst_outage_traces(n=15)
    write_jsonl(plain, bundles)
    gz = tmp_path / "archive.jsonl.gz"
    with gzip.open(gz, "wb") as out:
        out.write(plain.read_bytes())

    store_plain = ObservationStore(tmp_path / "plain.db")
    s_plain = observe(
        source=JsonlTraceSource(plain), store=store_plain, budget=100
    )

    store_gz = ObservationStore(tmp_path / "gz.db")
    s_gz = observe(source=JsonlTraceSource(gz), store=store_gz, budget=100)

    assert s_plain.events_new == s_gz.events_new == 15
    plain_rec = sum(c.recurrence_count for c in store_plain.list_clusters(kind="rule"))
    gz_rec = sum(c.recurrence_count for c in store_gz.list_clusters(kind="rule"))
    assert plain_rec == gz_rec == 15


# ---------- 8. Retention pruning bounds storage ---------------------


def test_retention_pruning_drops_events_but_keeps_clusters(tmp_path: Path) -> None:
    """`prune_events_older_than` shrinks the event table; clusters
    persist as aggregates. The store remains queryable after prune."""
    jsonl = tmp_path / "old.jsonl"
    write_jsonl(jsonl, burst_outage_traces(n=40))

    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=100)
    before_clusters = store.list_clusters(kind="rule")
    assert before_clusters
    before_recurrence = before_clusters[0].recurrence_count

    # Prune everything older than 0 days → drops all events.
    deleted = store.prune_events_older_than(retention_days=0)
    assert deleted == 40

    # Clusters still queryable, aggregates intact.
    after = store.list_clusters(kind="rule")
    assert len(after) == len(before_clusters)
    assert after[0].recurrence_count == before_recurrence


def test_storage_growth_is_bounded_per_run(tmp_path: Path) -> None:
    """Repeated observation runs on the same source must not bloat the
    database. Idempotency holds at the storage level too."""
    jsonl = tmp_path / "same.jsonl"
    write_jsonl(jsonl, burst_outage_traces(n=20))

    store_path = tmp_path / "obs.db"
    store = ObservationStore(store_path)
    source = JsonlTraceSource(jsonl)

    observe(source=source, store=store, budget=100)
    size_after_first = store_path.stat().st_size

    # Force replay 5 more times.
    for _ in range(5):
        store.save_cursor(source.name, "0")
        observe(source=source, store=store, budget=100)
    size_after_replays = store_path.stat().st_size

    # Replays may bump SQLite page allocation slightly but should not
    # multiply the file size. 2× headroom is generous.
    assert size_after_replays <= size_after_first * 2, (
        f"db size grew from {size_after_first} → {size_after_replays} "
        f"under replay; idempotency does not hold at the storage level"
    )


# ---------- 9. Digest readability under noise ----------------------


def test_digest_under_mixed_noise_is_bounded_in_size(tmp_path: Path) -> None:
    """A realistic noisy stream must not produce a digest with hundreds
    of clusters. The digest is for humans, not log spelunkers."""
    jsonl = tmp_path / "noise.jsonl"
    write_jsonl(jsonl, mixed_noise_traces(n=200))
    store = ObservationStore(tmp_path / "obs.db")
    summary = observe(source=JsonlTraceSource(jsonl), store=store, budget=500)

    digest = build_digest(store, summary=summary)
    rule_clusters = list(digest.rule_clusters)
    abstention_clusters = list(digest.abstention_clusters)

    # Bounded: the union must be small. 5 rules × 1-2 abstention codes
    # is the natural ceiling for our fixture mix.
    total_clusters = len(rule_clusters) + len(abstention_clusters)
    assert total_clusters <= 8, (
        f"digest produced {total_clusters} clusters from 200 traces — "
        f"this is cluster explosion under noise"
    )

    md = render_digest(digest)
    # Disclaimers always present.
    assert "What this digest is NOT" in md
    assert "Recurring patterns (rule-grounded)" in md
    # And the document is meaningfully bounded too.
    assert len(md) < 20_000, "digest markdown unexpectedly large under noise"


def test_digest_min_recurrence_filters_out_one_offs(tmp_path: Path) -> None:
    """`--min-recurrence 5` should hide singletons. Operator's first
    defence against noise."""
    jsonl = tmp_path / "mixed.jsonl"
    write_jsonl(jsonl, mixed_noise_traces(n=80))
    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=200)

    all_clusters = store.list_clusters(kind="any", min_recurrence=1)
    filtered = store.list_clusters(kind="any", min_recurrence=5)
    # The filter is monotonic: it never returns more than the unfiltered set.
    assert len(filtered) <= len(all_clusters)
    # And it actually removes singletons.
    for c in filtered:
        assert c.recurrence_count >= 5


# ---------- 10. Trust behaviour under low-quality input -------------


def test_healthy_traces_alone_produce_no_rule_clusters(tmp_path: Path) -> None:
    """An entire window of healthy traffic must not produce any
    rule-grounded cluster. Observation mode does not invent failures."""
    jsonl = tmp_path / "healthy.jsonl"
    write_jsonl(jsonl, [healthy_trace(f"ok-{i}") for i in range(30)])
    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=100)

    assert store.list_clusters(kind="rule") == []
    abstentions = store.list_clusters(kind="abstention")
    # Most likely no_rule_matched (single OK span, no anomaly).
    codes = {c.abstention_code for c in abstentions}
    assert codes <= {
        "no_primary_trace",
        "empty_telemetry",
        "no_rule_matched",
        "weak_evidence",
        "conflicting_hypotheses",
    }


def test_low_quality_telemetry_does_not_promote_rule_clusters(tmp_path: Path) -> None:
    """Telemetry with missing propagation (orphan spans throughout) must
    not produce rule-grounded clusters. The engine's quality assessment
    is diagnostic — but orphan spans + no retry/pool metadata simply
    leaves no rule to fire. The trust outcome: rule clusters stay empty
    on this shape, regardless of which band the assessor reports."""
    jsonl = tmp_path / "lowq.jsonl"
    write_jsonl(jsonl, [orphan_span_trace(f"orph-{i}") for i in range(25)])
    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=100)

    rule_clusters = store.list_clusters(kind="rule")
    assert rule_clusters == []
    # All 25 land somewhere — either abstention clusters, or the
    # quality-band distribution table. We do not require a specific
    # band assignment because that is the assessor's concern, not the
    # observation pipeline's.
    abstention = store.list_clusters(kind="abstention")
    total_clustered = sum(c.recurrence_count for c in abstention)
    assert total_clustered == 25, (
        "all orphan traces should land in abstention clusters; "
        "the engine must not silently drop them"
    )


# ---------- 11. Determinism: same input → same fingerprints ---------


def test_abstention_fingerprint_collapses_high_service_count(tmp_path: Path) -> None:
    """Regression for op002 (OTel Demo) finding: a multi-service mesh
    where different requests touch different SUBSETS of services must
    NOT produce one abstention cluster per unique service-set.

    The fingerprint is keyed on entry-service(s), not the full
    transitive service set. So 50 traces all entering at "frontend"
    but touching 4 different downstream subsets must collapse to ONE
    abstention cluster, not 4.
    """
    jsonl = tmp_path / "mesh.jsonl"
    bundles: list[dict] = []
    # Build 50 traces. All have entry-point span on "frontend".
    # Vary which downstream services are touched per trace — this is
    # exactly the OTel Demo pathology.
    base = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    downstream_combos = [
        ["cart"],
        ["cart", "product-catalog"],
        ["cart", "product-catalog", "recommendation"],
        ["payment", "currency"],
        ["payment", "currency", "shipping", "email"],
    ]
    for i in range(50):
        tid = f"mesh-{i:04d}"
        combo = downstream_combos[i % len(downstream_combos)]
        spans = [{
            "trace_id": tid,
            "span_id": f"f{i}",
            "parent_span_id": None,
            "service_name": "frontend",
            "operation_name": "GET /api/checkout",
            "start_time": base.isoformat(),
            "duration_us": 5000,
            "status": "OK",
            "status_message": "",
            "attributes": {},
            "events": [],
        }]
        for j, svc in enumerate(combo):
            spans.append({
                "trace_id": tid,
                "span_id": f"d{i}-{j}",
                "parent_span_id": f"f{i}",
                "service_name": svc,
                "operation_name": f"{svc}.handle",
                "start_time": base.isoformat(),
                "duration_us": 1000,
                "status": "OK",
                "status_message": "",
                "attributes": {},
                "events": [],
            })
        bundles.append({
            "trace_id": tid,
            "captured_at": base.isoformat(),
            "spans": spans,
            "logs": [],
        })
    write_jsonl(jsonl, bundles)

    store = ObservationStore(tmp_path / "obs.db")
    observe(source=JsonlTraceSource(jsonl), store=store, budget=100)

    abstention_clusters = store.list_clusters(kind="abstention")
    # All 50 traces share entry-point service "frontend" → one cluster.
    assert len(abstention_clusters) == 1, (
        f"high-service-count mesh produced {len(abstention_clusters)} abstention "
        f"clusters; expected exactly 1 because all traces share entry-point "
        f"service. This is the cardinality bug fixed during op002 validation; "
        f"if this test fails, fingerprint regressed to using full service_set."
    )
    assert abstention_clusters[0].recurrence_count == 50


def test_fingerprint_determinism_across_runs(tmp_path: Path) -> None:
    """Same input file processed twice into separate stores must yield
    identical fingerprint sets. Determinism at the cluster level is
    non-negotiable for cross-source comparison."""
    jsonl = tmp_path / "det.jsonl"
    write_jsonl(jsonl, cascading_failure_traces(n=30))

    fps_per_run: list[set[str]] = []
    for n in range(2):
        store = ObservationStore(tmp_path / f"obs-{n}.db")
        observe(source=JsonlTraceSource(jsonl), store=store, budget=100)
        clusters = store.list_clusters(kind="any")
        fps_per_run.append({c.fingerprint for c in clusters})

    assert fps_per_run[0] == fps_per_run[1]


# ---------- 12. No-drift smoke check --------------------------------
#
# This is a structural assertion. Phase A's identity is "observation
# only" — the module must not import side-effect-producing surfaces
# (PR comment renderer, GitHub integration, LLM client). If a future
# change accidentally pulls one of these into the observation pipeline,
# this test fails loudly.


def test_observation_module_does_not_import_side_effect_surfaces() -> None:
    import arip_core.observation as obs_pkg

    forbidden = {
        # Anything that writes to GitHub, sends a network call to
        # Anthropic, or otherwise reaches outside the local SQLite store.
        "arip_core.integrations.github",
        "arip_core.reporter.llm_summarizer",
    }

    import pkgutil

    seen_modules: set[str] = set()

    def _walk(pkg) -> None:
        for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__, prefix=pkg.__name__ + "."):
            if name in seen_modules:
                continue
            seen_modules.add(name)
            mod = __import__(name, fromlist=["*"])
            if ispkg:
                _walk(mod)

    _walk(obs_pkg)

    for mod_name in seen_modules:
        mod = __import__(mod_name, fromlist=["*"])
        src = getattr(mod, "__file__", "")
        if not src:
            continue
        text = Path(src).read_text()
        for f in forbidden:
            assert f not in text, (
                f"observation module {mod_name} imports forbidden "
                f"side-effect surface {f}"
            )
