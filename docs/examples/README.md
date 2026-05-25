# ARIP example outputs

Real artifacts from a clean two-run demo, frozen in this directory so
README + walkthrough + slides can link at concrete output without
needing a live stack.

Regenerate with: `bin/arip-e2e.sh` (run twice for the cross-run set).

## Investigation reports (one per failure pattern)

| File | Rule | Severity | What to look for |
|------|------|----------|------------------|
| [retry_storm-rca.md](retry_storm-rca.md) | `retry_storm` | high | 5 retry attempts with exponential backoff, amplification factor, downstream as root cause |
| [pool_exhaustion-rca.md](pool_exhaustion-rca.md) | `db_pool_exhaustion` | high | `db.pool.*` saturation signals, healthy query contrast, WARN log corroboration |
| [downstream_error-rca.md](downstream_error-rca.md) | `downstream_error` | high | ERROR chain across services, HTTP 500 surfaced cleanly |
| [concurrent_modification-rca.md](concurrent_modification-rca.md) | `concurrent_modification` | high | Two traces overlapping on same `order.id`, state transitions, WARN logs |

Each of these is what gets written to `reports/*.md` during a real
CI run; the JSON twin lives next to it in CI artifacts.

## CI surface

- [pr-comment.md](pr-comment.md) — the sticky comment ARIP posts on a
  GitHub PR. Single table at the top, one collapsible `<details>` block
  per failure. Renders inside GitHub's 64 KB soft limit; truncates the
  per-failure details first if the budget would be exceeded.

## Engine behaviour

- [abstention.md](abstention.md) — what the engine produces when the
  primary trace is not in the telemetry backend. The "I don't know"
  pathway, surfaced as a structured report section rather than silent
  failure or invented hypothesis.
- [fingerprint-cross-run.md](fingerprint-cross-run.md) — the contents
  of `.arip/memory.db` after two runs. Shows fingerprint stability,
  per-rule grouping, and the per-test history table that feeds the
  flaky classifier.

## Trace as ARIP sees it

- [jaeger-trace-retry-storm.md](jaeger-trace-retry-storm.md) — the raw
  span tree of a retry-storm trace, rendered as a text timeline. This
  is the same data the engine reads from Jaeger's `/api/traces/{id}`.

## Binary screenshots

Take these live when running the demo (see
[screenshots/README.md](screenshots/README.md) for the capture script
and the exact URLs):

- Jaeger UI showing a retry-storm trace fanned out
- Jaeger UI showing pool saturation timing
- GitHub PR with the sticky `arip-investigation` comment open
- Diff between two PR comment versions (rerun behaviour)
