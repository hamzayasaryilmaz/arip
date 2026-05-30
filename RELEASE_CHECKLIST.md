# Release Checklist

Per-release runbook. Walk top to bottom; do not skip rows. Each row
is a 30-second-to-2-minute check. Total: ~20 minutes.

## 1. Local validation

| ☐ | Check                                                                                    | Command / where                                                  |
|---|------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| ☐ | All unit tests pass                                                                      | `cd arip-core && uv run pytest`  (expect: 249 passed)            |
| ☐ | For major engine/rule/default changes: re-run field-test scenarios                       | See [docs/FIELDTEST.md](docs/FIELDTEST.md). 10 scenarios against a real OTel-Python stack; 9 expected to produce the same primary/hygiene outcome. |
| ☐ | Demo runner preflight catches missing tools                                              | Temporarily rename `uv` on PATH, run `bin/arip-demo.sh`          |
| ☐ | Demo runner self-bootstraps cleanly on a fresh clone                                     | Delete `tests/playwright/node_modules` and `arip-core/.venv`, then `bin/arip-demo.sh` |
| ☐ | `bin/arip-demo.sh` completes A → F                                                       | `ARIP_DEMO_NONINTERACTIVE=1 bin/arip-demo.sh`                    |
| ☐ | `bin/arip-e2e.sh` completes with PASS in < 60 s                                          | `bin/arip-e2e.sh`                                                |
| ☐ | All 4 failures produce a primary hypothesis (no abstention regression)                   | After demo: `sqlite3 .arip/memory.db "SELECT primary_rule_id, COUNT(*) FROM investigations GROUP BY primary_rule_id"` — expect 4 distinct rules |
| ☐ | Memory store accumulates fingerprints across runs                                        | Run demo twice; expect 8 investigations × 4 fingerprints         |
| ☐ | Empty-state PR comment renders cleanly                                                   | `uv run arip pr-comment /tmp/empty-dir` (expect "No failures investigated.") |

## 2. Repo hygiene

| ☐ | Check                                                                                    | Command / where                                                  |
|---|------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| ☐ | `.gitignore` covers all regenerated outputs                                              | `git status` after a demo run should show no untracked files inside `reports/`, `.arip/`, `node_modules/`, `arip-core/.venv/`, `tests/playwright/playwright-report.json`, `arip-pr-comment.md` |
| ☐ | `.env.example` is in sync with `docker-compose.yml`                                      | Read both; every env var the compose file uses has a documented default in `.env.example` (or a clear "informational only" note) |
| ☐ | All shell scripts have the executable bit                                                | `ls -la bin/ demo-env/failure-injector/scenarios/` (every `*.sh` should be `rwxr-xr-x`) |
| ☐ | All shell scripts use LF line endings                                                    | `file bin/*.sh demo-env/failure-injector/scenarios/*.sh` (no CRLF) |
| ☐ | No accidentally-committed regenerated files                                              | `git ls-files reports/ .arip/ arip-pr-comment.md` should return nothing |
| ☐ | No accidentally-committed secrets / API keys                                             | `git log --all -p \| rg -i "(api[-_]?key\|secret\|password)" \| head` (eyeball) |

## 3. Documentation integrity

| ☐ | Check                                                                                    | Command / where                                                  |
|---|------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| ☐ | All doc-internal markdown links resolve                                                  | Re-run the link checker (see below)                              |
| ☐ | All curated examples in `docs/examples/` reflect the latest engine output                | After a clean demo run, `diff` the report files vs `docs/examples/*-rca.md`; refresh as needed |
| ☐ | The PR comment example in `docs/examples/pr-comment.md` matches the current renderer     | After demo, `diff arip-pr-comment.md docs/examples/pr-comment.md`; refresh as needed |
| ☐ | README's "Failure scenarios shipped" table covers all 5 scenarios                        | Read README; cross-check vs `arip_core/engine/hypothesis.py` `default_rules()` |
| ☐ | ROADMAP "Phase 1 ✓ shipped" list matches what is actually in main                        | Read [ROADMAP.md](ROADMAP.md) Phase 1 section                    |
| ☐ | FAILURE_MATRIX matches the rule registry in INVESTIGATION_RULES                          | Both should list the same 5 rule_ids                             |

Link checker:

```python
python3 <<'PY'
import re, os, sys
ROOT = '.'
docs = []
for root, _, files in os.walk(f'{ROOT}/docs'):
    for f in files:
        if f.endswith('.md'):
            docs.append(os.path.join(root, f))
docs += [f'{ROOT}/README.md', f'{ROOT}/ROADMAP.md',
         f'{ROOT}/QUICKSTART.md', f'{ROOT}/DEMO_SCRIPT.md',
         f'{ROOT}/RELEASE_CHECKLIST.md']
checked, broken = 0, []
for path in docs:
    with open(path) as f: content = f.read()
    content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
    for m in re.finditer(r'\]\(([^)]+)\)', content):
        target = m.group(1)
        if target.startswith('http'): continue
        base = os.path.dirname(path)
        resolved = os.path.normpath(os.path.join(base, target.split('#')[0]))
        checked += 1
        if not os.path.exists(resolved):
            broken.append(f'  {path} -> {target}')
print(f'{checked} doc-internal links across {len(docs)} docs')
if broken: print('BROKEN:'); print('\n'.join(broken)); sys.exit(1)
print('all resolve ✓')
PY
```

## 4. GitHub workflow validation (REAL PR)

| ☐ | Check                                                                                    | How                                                              |
|---|------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| ☐ | Workflow runs on the PR                                                                  | Open a PR; watch Actions tab                                     |
| ☐ | Workflow completes in < 8 minutes                                                        | Actions tab → run summary                                        |
| ☐ | Sticky PR comment is posted with header `arip-investigation`                             | PR conversation                                                  |
| ☐ | Comment contains the summary table + `<details>` per failure                             | Open the comment                                                 |
| ☐ | Comment stays under 64 KB (no truncation note for 4 failures)                            | Open the comment                                                 |
| ☐ | Push a second commit → existing comment is **updated**, not duplicated                   | PR conversation should have one ARIP comment, not two            |
| ☐ | `arip-reports` artifact is downloadable                                                  | Actions → run summary → Artifacts                                |
| ☐ | Artifact contains `reports/` + `playwright-report.json` + `arip-pr-comment.md`           | Download + unzip                                                 |
| ☐ | Memory cache restores across runs (`Cross-run context` populated on 2nd run)             | Trigger 2 workflow runs on the same branch; 2nd run reports show "seen 1 time(s) before" |
| ☐ | Workflow does not require an `ANTHROPIC_API_KEY` to succeed                              | Repo with no secret should still produce reports (deterministic TL;DR) |
| ☐ | Workflow permissions are minimal                                                         | `.github/workflows/arip-investigate.yml` → `permissions:` block has only `contents: read` + `pull-requests: write` |

## 5. Screenshots (for README + docs)

Capture from a live demo run. See `docs/examples/screenshots/README.md`
for filenames + URLs.

| ☐ | Screenshot                                       | File                                                                 |
|---|--------------------------------------------------|----------------------------------------------------------------------|
| ☐ | Jaeger UI showing a retry_storm trace            | `docs/examples/screenshots/jaeger-retry-storm.png`                   |
| ☐ | Jaeger UI showing pool_exhaustion timing         | `docs/examples/screenshots/jaeger-pool-exhaustion.png`               |
| ☐ | Jaeger services list (all 4 services emitting)   | `docs/examples/screenshots/jaeger-services.png`                      |
| ☐ | GitHub PR with the sticky ARIP comment open      | `docs/examples/screenshots/pr-comment.png`                           |
| ☐ | Same PR after re-run (comment updated, not dup)  | `docs/examples/screenshots/pr-comment-rerun.png`                     |
| ☐ | Actions artifact summary                         | `docs/examples/screenshots/pr-artifact.png`                          |

## 6. Demo flow rehearsal

Before any external demo (livestream, video, talk):

| ☐ | Check                                                                                    |
|---|------------------------------------------------------------------------------------------|
| ☐ | Dry run `DEMO_SCRIPT.md` end-to-end ≤ 30 minutes before                                  |
| ☐ | Demo completes in ≤ 8 minutes following the script                                       |
| ☐ | All terminal sizes adequate (font ≥ 16 pt, narrow terminal does not wrap critical lines) |
| ☐ | Jaeger UI is loaded in a second window/tab, ready to go                                  |

## 7. Known limitations to surface in release notes

Honest list — anyone evaluating the project will look here first.

- **Local-first only.** No SaaS, no managed service. Telemetry path is
  Jaeger + Docker logs; production deployments substitute their own
  Tempo/Loki/k8s and write a thin client.
- **Playwright-only ingestion.** Other test runners would need their
  own collector layer (the `FailureEvent` schema is the contract).
- **Jaeger trace links assume `localhost:16686`.** The links inside
  PR comments work for someone running the demo locally; in CI they
  resolve to a transient container that is gone by the time the
  comment is rendered. Documented as MVP limitation; configurable
  via env var is on the deferred list.
- **No deterministic replay, no causal inference, no eBPF.**
  Explicitly deferred — see [docs/FUTURE_ARCHITECTURE.md](docs/FUTURE_ARCHITECTURE.md).
- **No statistical baselines.** Latency thresholds are hard-coded
  (e.g., `50ms`, `10× ratio`); good enough for the demo, insufficient
  for production heterogeneity.
- **Confidence scores are heuristic.** They reflect signal strength,
  not calibrated historical accuracy. Calibration loop is a
  Phase 2 item.

## 8. Publishing checklist

| ☐ | Check                                                                                    |
|---|------------------------------------------------------------------------------------------|
| ☐ | Repo description on GitHub set                                                           |
| ☐ | Repo topics / tags set (observability, playwright, rca, otel, …)                         |
| ☐ | LICENSE file present and visible                                                         |
| ☐ | README "Status" section reflects Phase 1 ✓ shipped                                       |
| ☐ | Initial release tag created (`v0.1.0`)                                                   |
| ☐ | Release notes pasted from this checklist's "Known limitations" + the v0.1.0 capability set |
| ☐ | First-time visitor can go from repo landing page → working demo in ≤ 15 minutes          |
