# Security Policy

ARIP is research-grade open-source engineering tooling at v0.1.0,
pre-first-real-engineer-pilot. It is **not production-ready**, but
the trust contract it enforces matters, and security issues are
taken seriously.

## What's in scope

| Surface | In scope for security reports |
|---|---|
| Engine reasoning paths (`arip_core/engine/`) | Yes — anything that could enable evidence-audit bypass, abstention-skip, or rule injection |
| Cross-run memory store (`arip_core/memory/store.py`) | Yes — SQL injection, path traversal, schema corruption |
| Observation store (`arip_core/observation/store.py`) | Same |
| Operator adapters (`bin/jaeger-export-to-bundles.py`, `bin/loki-export-to-logs.py`, `bin/tempo-export-to-bundles.py`) | Yes — input parsing vulnerabilities, command injection via filename |
| GitHub Actions workflows (`.github/workflows/`) | Yes — workflow injection, secret leakage |
| Bash scripts (`bin/*.sh`) | Yes — command injection via operator-controlled args |
| LLM summariser (`arip_core/reporter/llm_summarizer.py`) | Limited — the LLM never sees raw telemetry by design; report it if a path is found that violates this |

## What's out of scope (by design)

- Authentication / authorization — there isn't any. ARIP runs
  locally; there is no remote control plane.
- Network security beyond Jaeger / Loki HTTP — adapters read
  operator-provided files, not network endpoints.
- DoS via large input — the engine is bounded by `--budget` and
  per-trace try/except. A pathologically-large input is an
  operator concern, not a vulnerability.
- The demo stack (`demo-env/`) — Go services + Postgres + Redis
  for demonstration only; not intended for production exposure.

## Reporting a vulnerability

**Please do NOT open a public GitHub issue for security
vulnerabilities.**

Email: hamzayasaryilmaz@gmail.com

Include:

1. Affected component (e.g. "observation store SQL query in
   list_clusters")
2. Steps to reproduce — concrete commands or inputs that
   demonstrate the issue
3. Impact — what an attacker could do (evidence-audit bypass,
   data exfiltration, etc.)
4. Severity assessment if you have one

Expect an acknowledgment within 7 days. Fixes for confirmed
vulnerabilities ship as patch releases (e.g. v0.1.1).

## Disclosure timeline

- Day 0: report received
- Day ≤ 7: acknowledgment + initial triage
- Day ≤ 30: fix released OR clear timeline communicated
- Day ≤ 60: public advisory (CVE if applicable) — coordinated
  with the reporter

Researchers who follow responsible disclosure are credited in the
advisory unless they prefer otherwise.

## Hardening practices already in place

The project's existing security posture:

- **Bandit clean** on high/medium severity issues (low-severity
  asserts in test code are acknowledged false positives).
- **Apache-2.0 licensed** — no proprietary code paths.
- **No telemetry collected by the engine itself** — observe-mode
  pulls from operator-provided sources; the engine never phones
  home.
- **LLM confinement** — the optional Anthropic API call sees only
  pre-rendered hypothesis text, never raw spans or logs. Confined
  in `arip_core/reporter/llm_summarizer.py`; trust contract
  enforced by `tests/test_observation_stress.py::test_observation_module_does_not_import_side_effect_surfaces`.
- **SQL is parametrised** — all variable values use `?`
  placeholders. The one string-built WHERE clause is annotated
  `# nosec` with an explanation; clauses are from a fixed internal
  set, not user input.
- **Hashing intent is explicit** — SHA-1 in the observation source
  is annotated `usedforsecurity=False` (idempotency key, not
  security operation).
- **No `eval` / `exec` / `pickle` of untrusted data** anywhere in
  the codebase.
- **No subprocess shell=True** in any Python script.
- **Trace IDs hashed before storage** in the observation store
  (SHA-256, 16 hex chars) to keep raw production trace IDs out
  of the committed pilot archives.

## Pilot-archive PII discipline

Pilot archives in `docs/observe-pilot-archive/` are public. The
pilot kit explicitly requires:

- No raw `trace_id`s in any committed file (the store hashes them)
- No customer / order / account IDs in operation names without
  scrubbing
- No log line bodies that may contain PII
- No operator real name unless explicitly opted-in

If you find a committed pilot archive that violates these, please
report it via the channel above — it counts as a privacy/security
issue, not a docs issue.
