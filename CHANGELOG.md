# Changelog

All notable changes to this project are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/) and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (onboarding self-serve — `arip init` + `arip doctor`)

The first version of ARIP shipped with a manual onboarding path:
read 4 docs, study sample configs, hand-write a NormalizationConfig
YAML, then run preflight and iterate. Real-world feedback (and the
field-test reflection in `docs/FIELDTEST.md`) made it clear that
4-8 hours of hand-holding per new operator is the single largest
adoption friction.

Two new commands cut this to ~20 minutes of self-serve:

- **`arip init --from <BUNDLE> --out arip.yaml`** — inspect a
  sample JSONL trace bundle (the output of any
  `bin/*-export-to-bundles.py` adapter) and auto-generate a
  starter NormalizationConfig. Detects: business_keys (attributes
  named `*.id` carrying ID-shaped values across ≥2 services),
  expected_services_per_trace (distinct service names),
  expected_log_sources (services emitting logs), and
  handler_operation_patterns (HTTP-verb + handle_ prefixes on
  near-root spans). Every detected value carries an inline comment
  explaining the basis for the choice.

- **`arip doctor --from <BUNDLE>`** — per-rule diagnostic that
  reports for each of the 5 shipped rules: would_fire / blocked /
  silent, what required signals are present in this sample, what
  optional signals would lift confidence, and exactly which next
  step the operator should take. Auto-discovers `arip.yaml` in
  cwd if `--config` not specified.

Both commands work on the same JSONL bundle file format the
adapters produce, so an operator can sample one real trace bundle
and have a working config + signal census in a single pass.

Implementation lives in a new `arip_core/onboarding/` package
(auto_config.py + doctor.py + bundle_loader.py). 10 regression
tests in `tests/test_onboarding.py`.

Also: `arip observe` now auto-discovers `arip.yaml` / `arip.yml` /
`.arip/config.yaml` in cwd when `--config` is omitted (saves
operators from typing `--config` on every run).

### Added (commercial scaffolding — services-around-OSS path)

- **`docs/COMMERCIAL_OFFERINGS.md`** — master doc defining 4
  service offerings: A (Integration $5-15k), B (Telemetry Hygiene
  Audit $3-8k), C (Paid Pilot $5-10k — recommended starter), D
  (Support contract $12-36k/yr). Includes qualifier questions,
  what-NOT-to-sell anti-goals, and meeting prep checklist.
- **`docs/ARIP_ONE_PAGER.md`** — print-and-leave-behind for CTO
  meetings. Honest comparison table vs "AI RCA tools", explicit
  list of what ARIP is NOT, honest gaps section (async messaging,
  5 rules narrow, requires distributed tracing).
- **`docs/COMMON_OBJECTIONS_FAQ.md`** — honest objection-handling
  reference covering "we have Datadog already", "is this AI?",
  "5 rules sounds limiting", funded?, customer references, refund
  policy, etc. No marketing — direct answers including when to
  walk away.
- **`docs/templates/PAID_PILOT_SOW.md`** — Statement of Work
  template for Offering C (14 sections incl. scope, deliverables,
  customer responsibilities, refund policy, IP, confidentiality).
- **`docs/templates/INTEGRATION_ENGAGEMENT.md`** — SOW template
  for Offering A (11 sections + bug-fix window terms + scope
  multipliers).
- **`docs/templates/TELEMETRY_HYGIENE_AUDIT_REPORT.md`** — Offering B
  deliverable template (11 sections: distributed tracing baseline,
  span tree propagation, service coverage, log-trace correlation,
  business-key propagation, rule readiness, prioritized fixes, ARIP
  fit assessment). Three honest verdict examples (GOOD/MIXED/POOR).
- **`docs/PRODUCTION_DEPLOYMENT.md`** — operator deployment guide.
  3 topology options (in-CI, scheduled GHA observe-mode, self-hosted),
  step-by-step Option 1 production setup (7 steps prereq → handover),
  operations + disaster recovery + when NOT to deploy.

### Added (adapter framework + 3 OTel-compatible adapters)

- **`bin/adapter-template.py`** — copy-and-modify template for
  authoring new operator-side adapters. Helpers: `_dig`,
  `_first`, `_to_iso` (handles epoch ns/ms/s + ISO),
  `_duration_us` (heuristic ns/us/ms), `_status` (normalises
  string/int/dict). `_FieldConfig` overridable via CLI;
  `_hits_from_file` with JSON / JSON-array / NDJSON fallback;
  `_hits_from_vendor` skeleton for live API path. Non-zero exit +
  warning when zero bundles produced.
- **`docs/WRITING_AN_ADAPTER.md`** — adapter authoring guide
  (8 steps from format-understanding to documentation). Quality bar
  checklist + "what you should NOT do" anti-goal protections (no
  invented telemetry, no engine modifications, no anti-goal drift).
- **`bin/honeycomb-export-to-bundles.py`** — Honeycomb adapter.
  Field defaults `trace.trace_id` / `trace.span_id` /
  `trace.parent_id` / `service.name` / `name` / `timestamp` /
  `duration_ms` (× 1000 → us) / `status_code`. Multi-format status
  handling (boolean `error`, string ERROR, OTLP numeric). Live
  Honeycomb Query API path (create query → poll → fetch) included
  but unverified.
- **`bin/grafana-cloud-export-to-bundles.py`** — wrapper around
  Tempo adapter that handles Grafana Cloud auth (basic auth via
  `stack_id:api_key`) + two-step search → fetch pattern. Delegates
  actual conversion to `bin/tempo-export-to-bundles.py` via
  subprocess. Live API path unverified.
- **`bin/aws-xray-to-bundles.py`** — AWS X-Ray segments → bundles.
  `_xray_trace_id_to_hex` strips `"1-"` prefix + dashes.
  `_walk_segments` recursively flattens subsegments to spans with
  `parent_span_id` chaining. Handles `Fault` / `Error` / `Throttle`
  booleans → ERROR status. Flattens `Http` / `Aws` / `User` /
  `Annotations` / `Metadata` sections to dotted-key attributes
  (PascalCase keys preserved). Tested against synthetic X-Ray
  fixtures; live AWS pull unverified.

### Added (adapter inventory)

- **`docs/adapter-roadmap.md`** — operator authority on "do we have
  an adapter for X?". Three sections:
  - **Currently shipped** (9 adapters with verified-test-status:
    Jaeger / Tempo / Loki / ES traces / ES logs / Honeycomb /
    Grafana Cloud Tempo / AWS X-Ray / directory of JSON bundles)
  - **On-request** (11 vendor sketches with field mapping +
    effort estimate + billing range: Datadog APM, New Relic APM,
    Splunk APM, Splunk Cloud logs, Dynatrace, AppDynamics, Sumo
    Logic, Logz.io, Azure App Insights, GCP Cloud Trace, AWS
    CloudWatch Logs, custom internal logging)
  - **Explicitly NOT pursuing** (Slack/Teams notifications, Jira
    tickets, PagerDuty paging, auto-PR with fixes, Sentry, hosted
    SaaS, GUI — each with anti-goal citation)
  Prioritization rule: paid pilot demand drives, not popularity.

### Added (test coverage for new adapters)

- 8 tests for Honeycomb adapter (`test_honeycomb_adapter.py`):
  event grouping, duration_ms → us, status-code variants (string
  ERROR / boolean / OTLP numeric), unparseable-doc warning,
  field-override flow, JSONL input format.
- 7 tests for AWS X-Ray adapter (`test_xray_adapter.py`):
  single-segment conversion, subsegment flattening with
  `parent_span_id` chain, Fault/Error → ERROR, Http section
  flattened to dotted-key attributes (PascalCase preserved),
  X-Ray trace_id `"1-..."` format conversion, empty-input
  warning.

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
