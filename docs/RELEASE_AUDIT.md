# Pre-push release audit — observe-mode + trust-layer + pilot-kit snapshot

Audit performed before the first GitHub push of the ARIP repository.
Goal: ship a reproducible, leak-free, fresh-clone-runnable snapshot
of the current state (engine + observe-mode + trust layer +
portability + pilot kit) at v0.1.0.

This document is **not** a release-engineering plan. It is a one-time
checklist for the initial commit and the recommended push sequence.

## Headline state

- Branch: `master` (recommend rename to `main` before first push)
- Commits on branch: **0** — first commit pending
- Untracked top-level entries: 17 (all intentional, none ignored)
- Ignored entries detected: `.arip/memory.db`, `reports/`,
  `arip-pr-comment.md`, `tests/playwright/node_modules/`,
  `tests/playwright/playwright-report.json`,
  `tests/playwright/test-results/` — all properly caught by
  `.gitignore`
- Test suite: **145/145 passing**
- Discovered local artefacts to NOT commit (verified ignored): see
  list in section *"What is correctly NOT being committed"* below

## What is correctly being committed

Top-level (17 entries, all intentional):

| Entry | Why |
|---|---|
| `.env.example` | Default env vars; `.env` is gitignored |
| `.github/` | GitHub Actions workflow for `arip investigate` |
| `.gitignore` | The contract; comprehensive |
| `ARIP_CLAUDE_CODE_MASTER_PROMPT.md` | Original build spec — kept for archaeology |
| `DEMO_SCRIPT.md` | Demo narration |
| `PILOT.md` | Investigation-mode pilot kit |
| `QUICKSTART.md` | Fresh-clone onramp |
| `README.md` | Entry doc |
| `RELEASE_CHECKLIST.md` | Per-release runbook |
| `ROADMAP.md` | Phased plan + Phase A status |
| `arip-core/` | Python engine + tests + configs |
| `bin/` | 7 operator scripts (demo + observe-mode + adapters) |
| `demo-env/` | Go services + OTel Collector + Postgres + Redis |
| `docker-compose.yml` | Demo stack |
| `docs/` | All documentation including observe-mode kit |
| `pilot-archive/` | Investigation-mode pilot archive (empty + `_template/`) |
| `tests/` | Playwright integration tests + (eventually) shared fixtures |

Inside `docs/`:
- `observe-pilot-archive/` is committed with `README.md` +
  `_template/` only — no pilot data yet (`op001`, `op002`, … land
  after real pilots)

## What is correctly NOT being committed

`.gitignore` verified to catch all of:

- `.arip/memory.db` — local cross-run memory store
- `.arip/observation-*.db` — per-pilot observation stores
- `reports/` — regenerated investigation outputs
- `arip-pr-comment.md` — rendered per-run, regenerated
- `.env` — local env overrides (`.env.example` IS committed)
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `arip-core/.venv/` — Python local state
- `tests/playwright/node_modules/`, `tests/playwright/playwright-report.json`,
  `tests/playwright/test-results/` — Playwright local state
- `.DS_Store`, `.vscode/`, `.idea/`, `*.swp` — editor/OS junk
- `*.log`, `.tmp/` — temp files

## Pilot-safety / leak check

Pre-push leak audit:

| Risk | Status |
|---|---|
| Raw production telemetry committed | None present — all fixtures are synthetic, all pilot-archive templates carry `_comment` placeholders only |
| Real `trace_id`s, customer IDs, internal hostnames | None present |
| Secrets in workflow files | Only `${{ secrets.ANTHROPIC_API_KEY }}` reference — no secret values |
| Secrets in `.env.example` | None — all values are demo defaults pointing at localhost or docker-compose service names |
| Local SQLite DBs | All ignored (`.arip/*.db`) |
| Rendered digests / reports | All ignored (`reports/`, `arip-pr-comment.md`) |
| Screenshots / video assets | None present |
| Pilot archives | `pilot-archive/` and `docs/observe-pilot-archive/` contain only `README.md` + `_template/`; no real pilot data |

The repository is **pilot-safe to push** — no operator will leak real
telemetry on first commit.

## Fresh-clone reproducibility

Walked end-to-end:

```
git clone <repo-url> arip && cd arip
docker compose up -d --wait                # demo stack
( cd tests/playwright && npm install )     # Playwright
( cd arip-core && uv sync --extra dev )    # Python engine
bin/arip-demo.sh                            # narrated demo
```

For observe-mode:

```
bin/observe-self-audit.sh /tmp/your-bundles.jsonl     # 30-sec check
bin/run-observe-pilot.sh /tmp/your-bundles.jsonl op001 # full pilot
```

Verified:

- `README.md` "In 15 minutes" block points at `bin/arip-demo.sh` ✓
- `QUICKSTART.md` covers the full onramp ✓ — now also includes
  observe-mode rows (added during audit)
- `README.md` repo-layout block now mentions all 7 `bin/` scripts
  including the 4 observe-mode ones (added during audit)
- `README.md` test count updated `62 → 145` to reflect actual
  passing test count (added during audit)
- `bin/run-observe-pilot.sh` smoke-tested end-to-end against
  `/tmp/bundles-joined.jsonl` — idempotent, archives correctly,
  per-pilot store path correct

## Doc accuracy fixes applied during audit

These were stale and have been corrected — operator-facing files
now describe the actual state:

1. `README.md` "Status" block: test count `62/62` → `145/145` with
   breakdown (calibration benchmark + observation stress + ingestion
   validation)
2. `README.md` table of contents: added row for observe-mode docs
   trio (`OBSERVE_MODE.md` + `INGESTION_GUIDE.md` + `OBSERVE_PILOT_KIT.md`)
3. `README.md` repo layout: added all 4 observe-mode `bin/` scripts
4. `QUICKSTART.md` "Where to go next": added observe-mode + pilot
   runner rows
5. `README.md` removed line about "61 doc-internal markdown links" —
   stale count; doc set grew significantly and recounting is not the
   most important pre-push task

## Outstanding items NOT addressed in this audit

These are flagged but not changed — they are operator decisions, not
audit fixes:

1. **Branch rename `master` → `main`.** Recommend doing it before
   first push so the default branch matches the upstream convention
   (and what `CLAUDE.md` already declares as the main branch). After
   `git init` and before first push:
   ```
   git branch -m master main
   ```
2. **License: TBD.** `README.md` says `License: TBD.` — pick one
   before public push. MIT or Apache-2.0 are the obvious candidates
   for the deterministic-engine + operator-tooling profile.
3. **`pyproject.toml` version.** Already at `0.1.0` — no action.
4. **Doc-link validation** — was 61 internal links at v0.1.0-prep;
   audit did not re-run a link-check pass. Run before push if you
   want certainty:
   ```
   # quick markdown link check (any of: lychee, markdown-link-check)
   ```

## Recommended push sequence

### 1. Pre-commit prep (one-time)

```bash
# Branch hygiene
git branch -m master main

# Confirm clean state (no surprise modifications)
git status --short
git status --ignored --short | grep '^!!' | head -20   # sanity-check ignores

# Confirm tests green
( cd arip-core && uv run pytest -q )

# Confirm observe-mode smoke
bin/observe-self-audit.sh /path/to/any-bundles.jsonl   # optional
```

### 2. Initial commit

A single, large, **honest** initial commit. Don't fake a fictional
history — there is none. The commit captures the v0.1.0 snapshot
as built.

```bash
# Stage everything tracked (gitignored items are already excluded)
git add .

# Verify staged set is what you expect
git status --short

# Commit
git commit -m "$(cat <<'EOF'
Initial commit — ARIP v0.1.0 (Phase 1 MVP + Phase A observation)

What this snapshot contains:

  - Deterministic 5-rule investigation engine (retry_storm,
    db_pool_exhaustion, downstream_error, concurrent_modification,
    latency_vs_db) with evidence-audit, 5 abstention codes, and a
    10-scenario calibration benchmark.
  - Phase A observation mode (read-only, cursor-based, idempotent):
    arip_core/observation/ module, JSONL + directory sources,
    cluster store, markdown digest. Validated under synthetic noise
    (15 stress tests) and real-world export shapes (9 ingestion
    tests). Two narrow fingerprint-stability corrections applied
    during validation, both pinned by regression tests.
  - Operator tooling: 4 observe-mode bin/ scripts (Jaeger adapter,
    Loki adapter, self-audit, single-command pilot runner).
  - Pilot kits: investigation-mode (PILOT.md) and observation-mode
    (docs/OBSERVE_PILOT_KIT.md) — both with archive skeletons,
    feedback templates, and recruitment packages.
  - Trust contract: positioning gates (POSITIONING.md), no-drift
    module-import test, candidate-test generation explicitly gated
    to Phase B/C/D trigger conditions (FUTURE_ARCHITECTURE.md #11).
  - 145/145 unit tests passing. Demo end-to-end ≤ 16 s.
EOF
)"
```

### 3. Tag the snapshot

Lightweight tag for the v0.1.0 snapshot — no GitHub release UI
populated, just the tag:

```bash
git tag v0.1.0
```

If you want a slightly richer annotation for `git show v0.1.0`:

```bash
git tag -a v0.1.0 -m "v0.1.0 — Phase 1 MVP + Phase A observation, pre-first-pilot snapshot"
```

### 4. Push

```bash
# Add the remote (whatever URL you created)
git remote add origin git@github.com:<your-org>/arip.git

# Push main + tag in two commands so issues are easy to read:
git push -u origin main
git push origin v0.1.0
```

### 5. Post-push verification

After GitHub shows the repo:

- Open `README.md` on GitHub — confirm the "In 15 minutes" block
  renders and links work
- Open `docs/OBSERVE_PILOT_KIT.md` — confirm cross-links resolve
- Open `.github/workflows/arip-investigate.yml` — confirm GitHub
  shows the workflow under "Actions"
- Trigger a manual workflow run (`workflow_dispatch`) once to confirm
  CI actually executes; only push subsequent commits after this works

If anything breaks on GitHub, fix in a new commit. Do not force-push
over the initial commit — the tag would dangle.

## Stable snapshot recommendation

**Snapshot:** `v0.1.0` after the initial commit.
**Branch:** `main`.
**Tag policy:** lightweight tag at the commit; no GitHub Release UI
populated (defer until ≥ 3 observation-mode pilots have validated
the trust contract under real telemetry — see
[ROADMAP.md](../ROADMAP.md) Phase 2 entry criteria).
**License:** decide before push (TBD in README).

This snapshot is the **pre-first-pilot baseline**. The next
meaningful tag is `v0.2.0` after `op002` (first real engineer
pilot) lands in `docs/observe-pilot-archive/` and synthesis is run.

## What this audit deliberately did NOT do

Out of scope by user direction — all of these are deferred:

- Set up release engineering / packaging / PyPI publishing
- Set up Docker registry / image publishing
- Expand GitHub Actions (no new workflows; existing `arip-investigate.yml` stays as-is)
- Configure issue templates / PR templates / CODEOWNERS
- Add a CONTRIBUTING.md
- Add a CHANGELOG.md (the initial commit message IS the changelog for v0.1.0)
- Run automated security scanning / SBOM generation
- Migrate to a different branch protection / merge policy

These are all reasonable items for a later release-engineering pass.
Doing them now would over-engineer a pre-first-pilot snapshot.

## Audit verdict

**Ready to push** with the sequence in section *"Recommended push
sequence"* above. Two operator decisions outstanding before push:

1. Rename `master` → `main`
2. Pick a licence

Both are 1-minute decisions. Everything else is in place.
