# Contributing to ARIP

ARIP is a **deliberately narrow** project. Before you propose a
change, please read [docs/POSITIONING.md](docs/POSITIONING.md) — it
lists what ARIP intentionally is NOT (no APM, no dashboard, no
alerting, no autonomous agent, no broad connector ecosystem). The
project's positioning is part of its design; PRs that drift toward
any of those anti-goals will be declined regardless of code quality.

If you want to propose a capability that would fall outside the
current scope, please open an issue describing the **trigger
condition** (what observable user need would justify it) and we'll
discuss whether it belongs in `docs/FUTURE_ARCHITECTURE.md` or out
of scope entirely.

## Getting set up

```bash
git clone https://github.com/hamzayasaryilmaz/arip.git
cd arip/arip-core
uv sync --extra dev
uv run pytest -q     # should be 191/191 green
uv run ruff check .  # should be clean
```

If `uv` is new to you, install via the one-liner at
<https://docs.astral.sh/uv/>.

## What "good" looks like for a PR

1. **One concern per PR.** Refactors mixed with bug fixes are
   harder to review and harder to revert.
2. **Tests for changed behaviour.** Especially regression tests
   when fixing a defect (see `tests/test_observation_stress.py`
   for the pattern — the test docstring names the defect and the
   conditions under which it would re-emerge).
3. **No new abstractions without evidence.** ARIP is small (~6k
   LoC) on purpose. New base classes, interfaces, plug-in points
   need a concrete reason today, not a hypothetical future one.
4. **`pytest` and `ruff check` both pass.** CI enforces this; check
   locally first.
5. **CHANGELOG.md entry** under `[Unreleased]` describing what the
   PR does in a sentence or two.
6. **No dependency adds without strong justification.** Each new
   dependency expands the supply-chain surface and weakens
   reproducibility.

## Trust-contract changes are special

Any change to:
- the abstention layer (`arip_core/engine/abstention.py`)
- the evidence audit (`arip_core/engine/evidence_audit.py`)
- the calibration benchmark
  (`tests/test_calibration_benchmark.py`)
- the fingerprinting algorithm
  (`arip_core/memory/fingerprint.py`,
  `arip_core/observation/clustering.py`)
- the no-drift import test
  (`tests/test_observation_stress.py::test_observation_module_does_not_import_side_effect_surfaces`)

...is **trust-layer material**. PRs touching these need:

- A clear explanation of WHY the change is necessary
- A regression test that would catch the change being silently
  reverted
- Sign-off that the change does not weaken the contract (e.g. does
  not relax `MIN_EVIDENCE_KINDS`, does not loosen the conflict
  threshold without strong empirical reason)

These get extra scrutiny on purpose — they are the moat.

## Validation discipline

The project has a strong validation discipline that PRs should
respect:

- **Synthetic fixtures are not validation.** When adding a new
  rule, write the calibration-benchmark scenario first; the
  scenario is what locks the behaviour in.
- **`opNNN` pilot archives** carry a NO-HUMAN-OPERATOR disclaimer
  unless the archive captures a real engineer using observe-mode
  on their own telemetry. Runner-self-pilots are useful but
  explicitly labelled.
- **Phase 2 entry gate** requires ≥ 3 real-engineer pilots clearing
  thresholds in `docs/PILOT_METRICS.md`. Runner-self-pilots do
  not count.

## Testing

Test suite (191 tests, ~2 seconds):

```bash
uv run pytest -q
```

Coverage (currently 71%):

```bash
uv run pytest --cov=arip_core --cov-report=term-missing
```

End-to-end smoke (requires Docker):

```bash
bin/arip-demo.sh
```

Observe-mode smoke (no Docker; uses any JSONL trace bundle):

```bash
bin/observe-self-audit.sh path/to/bundles.jsonl
```

## Lint + style

```bash
uv run ruff check arip_core tests
uv run ruff format arip_core tests   # optional
```

Lint config is in `pyproject.toml` `[tool.ruff]`. The selected rule
set (F, E, W, I, B, UP, SIM, RUF) catches real bugs, modern-Python
suggestions, and import hygiene. Style is mostly auto-fixed; the
rules we deliberately ignore are documented inline.

## Security

If you discover a security issue, please follow [SECURITY.md](SECURITY.md)
(do not open a public issue first).

## Reviewing scope before contributing

The most likely reasons a PR would be declined regardless of code
quality:

| PR adds… | Why declined |
|---|---|
| Dashboard / web UI | Anti-goal in POSITIONING.md |
| Alerting / pager / Slack integration | Anti-goal |
| Auto-remediation or auto-PR-merge behaviour | Anti-goal |
| Adapter for a new APM / observability vendor without an operator who needs it | "Broad connector ecosystem" anti-goal |
| New rule without a calibration benchmark scenario | Validation discipline |
| Change that relaxes abstention thresholds without empirical justification | Trust-layer change without trust-layer reasoning |
| LLM-driven analysis path (rather than the existing TL;DR paraphrase) | Anti-goal — engine reasoning must stay deterministic |

If you're unsure whether your idea fits, open an issue first
rather than building it.

## What we love receiving

- **Real-world telemetry pathology reports** added to
  `docs/TELEMETRY_PATHOLOGIES.md` from genuine pilots
- **Bug fixes** with regression tests
- **Doc improvements** especially for the operator-facing surfaces
  (`docs/OBSERVE_MODE.md`, `docs/INGESTION_GUIDE.md`,
  `docs/OBSERVE_PILOT_KIT.md`)
- **Adapter PRs** for ingestion sources that an operator
  genuinely uses (not speculative)
- **First-real-engineer pilots** filed under
  `docs/observe-pilot-archive/opNNN/` per the existing kit

## Communication

- Issues: <https://github.com/hamzayasaryilmaz/arip/issues>
- Use issues to discuss design before PRs that touch trust-layer
  material or that propose new capabilities

Thanks for reading. Keep PRs focused, tests honest, and scope
narrow.
