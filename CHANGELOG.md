# Changelog

All notable changes to this project are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/) and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (robustness pass — telemetry hygiene + ES support)

- **Telemetry prerequisite gate**
  (`arip_core/quality/prerequisite.py`). `arip observe` now fail-fasts
  on telemetry that's not distributed-tracing-shaped (`no_spans`,
  `no_trace_id`, `no_propagation`) with a specific operator next-step
  hint instead of producing nonsense. Strict by default;
  `--skip-prerequisite-check` opt-out available.
- **Telemetry hygiene findings**
  (`arip_core/quality/hygiene.py`). Every observe-mode run now
  surfaces concrete gaps the operator can close:
  - Span-tree gaps (orphan spans → likely uninstrumented service)
  - Service-coverage assertion (operator-declared
    `expected_services_per_trace` not all present)
  - Log-source completeness (`expected_log_sources` missing)
  - Business-key propagation gap (entry-point has key but downstream
    doesn't → cross-trace correlation will break for this request)
- **Business-key alias chains** (`NormalizationConfig.business_key_aliases`).
  Handles ID translation across services — operator declares e.g.
  `order.id: [payment.order_ref, shipment.order_no]` and ARIP follows
  any of those when doing cross-trace correlation.
- **Abstention next-step hints** (`AbstentionReason.next_step` property).
  Each of the 5 abstention codes now carries a templated, actionable
  next-step pointing at the specific telemetry-hygiene action that
  would let the rule fire.
- **Elasticsearch operator adapters**:
  `bin/elasticsearch-traces-to-bundles.py` (spans/APM Server) and
  `bin/elasticsearch-logs-to-bundles.py` (logs joined by trace_id).
  Configurable field mapping; handles flat + nested ES schemas;
  three input formats (raw ES response, JSON array, NDJSON); both
  live ES query and pre-pulled file modes.
- **Pipeline-wide cross-trace lookup uses aliases**
  (`TimelineBuilder.build`). When asking Jaeger for sibling traces,
  ARIP now queries every configured business_key attribute + alias,
  not just the first one.
- **Digest renders prerequisite failure + hygiene findings**
  prominently — operator sees gaps at the top of the digest, before
  any (empty) recurring-patterns table.

### Added (test coverage)

- 9 tests for the prerequisite gate (`test_prerequisite.py`)
- 14 tests for hygiene findings (`test_hygiene.py`)
- 10 tests for Elasticsearch adapters (`test_es_adapter.py`)
- Tests cover the full failure matrix (no_spans, no_trace_id,
  no_propagation), per-finding cases (service coverage, log source,
  alias-based business key), and ES adapter behaviour (NDJSON
  fallback, nested fields, OTLP status codes, epoch_millis
  timestamps, unmatched-log surfacing).

### Fixed

- ES logs adapter previously silently dropped logs whose trace_id
  didn't match any bundle (matched by ID-presence, not by
  trace-existence). Now they go to `--unmatched-out` like logs with
  no trace_id at all.
- ES adapters' NDJSON parsing was masked by an earlier JSON-decode
  attempt that consumed the input on failure. Fall-through pattern
  added.

### Added (previously)

- Cypress test framework support (`arip_core/collector/cypress_listener.py`).
  CLI `arip investigate` auto-detects Playwright vs Cypress via the
  report shape; `--framework` flag forces a parser.
- New operator adapter `bin/tempo-export-to-bundles.py` for Grafana
  Tempo's OTLP-JSON wire format (Tempo is NOT Jaeger-compatible —
  separate adapter required). 7 unit tests pinning the conversion.
- GitHub Actions workflow template for observe-mode:
  `.github/workflows/arip-observe.yml.example` (scheduled cron,
  sticky issue comment, artifact upload, three telemetry-source
  options).
- Pilot runner regex now accepts `opNNN[a-z]?` suffix for follow-up
  runs on the same system (e.g. `op002` baseline vs `op002b` with
  fault injection).
- Five new pilot archives: op001 (HotROD), op002 (OTel Demo
  healthy), op002b (OTel Demo + fault injection), op002c (OTel
  Demo + fault injection + Loki logs joined), op003 (Tempo). All
  carry explicit NO-HUMAN-OPERATOR disclaimers — runner-self-pilots,
  not real-engineer pilots.
- New abstention-fingerprint regression test ensuring high-
  service-count meshes collapse to one cluster per entry service.
- Test coverage measurement (`pytest-cov` in dev extras).
- Ruff lint configuration (`pyproject.toml` `[tool.ruff]`).
- Test suite hardening: `tests/test_playwright_listener.py` (9 tests
  — previously 0 coverage), `tests/test_markdown_writer.py` (12 tests
  — previously 0 coverage).
- Meta-docs: this `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.

### Changed

- `_abstention_fingerprint` now uses entry-point services only
  (root spans + spans whose parent is missing from the bundle)
  instead of the full transitive service set. Caught by op002
  validation: 16-service mesh produced 23 distinct clusters from
  291 traces; post-fix produces 8 clusters. Docstring expanded
  with op002 rationale.
- `arip investigate` now accepts both Playwright and Cypress JSON
  reports. Default behaviour unchanged; auto-detect chooses
  parser. Operators can override with `--framework`.
- `pyproject.toml` modernised: added `license`, `authors`,
  `classifiers`, `keywords`, `[project.urls]`. Added explicit
  `[tool.pytest.ini_options]` (replaces ad-hoc config), `[tool.ruff]`,
  `[tool.coverage.*]`.
- `README.md` Status block updated for 191 tests + new validations.

### Fixed

- **Regression in `arip preflight`** introduced by the Cypress
  Phase B refactor: `parse_report` was undefined after the
  collector module restructure. Now correctly dispatches to
  cypress / playwright listener via `detect_report_kind`.
- **Pipeline cursor crash on fresh source + empty bundle cursor**:
  `observe()` previously passed `None` to `save_cursor`, which
  would crash the NOT NULL SQLite column. Now silently skips the
  save when the cursor cannot be advanced. Regression test added.
- **CLI loop-variable shadowing** in `_cmd_preflight`: `c` was
  used twice (once for `SignalCoverage`, once for `RuleContract`).
  Renamed to `contract` in the second loop. Caught by mypy strict.
- Dead code in `engine/rules/retry_storm.py`: removed unused
  `attempts` and `consistent_reason` locals. Behaviour unchanged
  (`truly_persistent` was the intended gate; comment clarified).
- Five `f-string` literals without placeholders converted to plain
  strings (cosmetic).
- Eight unused imports removed across `arip_core/` and `tests/`.
- Bandit-flagged `hashlib.sha1` in observation source explicitly
  annotated with `usedforsecurity=False` (idempotency key, not
  security). Bandit-flagged SQL string concatenation in
  `ObservationStore.list_clusters` annotated `# nosec B608`
  (fixed clauses only; all values via `?` placeholders).

## [0.1.0] — 2026-05-26

Initial public release. See
[docs/RELEASE_AUDIT.md](docs/RELEASE_AUDIT.md) for the pre-release
audit + push sequence.

### Added

- Deterministic 5-rule investigation engine: `retry_storm`,
  `db_pool_exhaustion`, `downstream_error`,
  `concurrent_modification`, `latency_vs_db`. Evidence audit,
  5 abstention codes (`no_primary_trace`, `empty_telemetry`,
  `no_rule_matched`, `weak_evidence`, `conflicting_hypotheses`),
  10-scenario calibration benchmark.
- Phase A observation mode (read-only, cursor-based, idempotent):
  `arip_core/observation/` module, JSONL + directory sources,
  cluster store, markdown digest. Validated under synthetic noise
  (15 stress tests) and real-world export shapes (9 ingestion
  tests). Two narrow fingerprint-stability corrections caught +
  fixed during validation, both pinned by regression tests.
- Operator tooling: 4 observe-mode `bin/` scripts (Jaeger
  adapter, Loki adapter, self-audit, single-command pilot runner).
- Pilot kits: investigation-mode (`PILOT.md`) and observation-mode
  (`docs/OBSERVE_PILOT_KIT.md`) — both with archive skeletons,
  feedback templates, recruitment packages.
- Trust contract enforcement: positioning gates
  (`docs/POSITIONING.md`), no-drift import test, candidate-test
  generation explicitly gated to Phase B/C/D trigger conditions
  (`docs/FUTURE_ARCHITECTURE.md` #11).
- Apache-2.0 LICENSE.
- 145/145 unit tests passing.
- GitHub Actions CI for `arip investigate` against the demo stack.

[Unreleased]: https://github.com/hamzayasaryilmaz/arip/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hamzayasaryilmaz/arip/releases/tag/v0.1.0
