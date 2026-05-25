# ARIP Architecture

```
                      Playwright tests fail
                              │
                              ▼
                ┌────────────────────────────┐
   Phase 2     │   FailureEvent              │
   COLLECTOR  │   (test_name, trace_id,     │  ◀── arip_core/collector/
              │    order_id, assertion, …)  │
              └─────────────┬───────────────┘
                              │
                              ▼
              ┌────────────────────────────┐
   Phase 3   │   CorrelatedTelemetry       │
   CORRELA-  │   ┌────────────────────┐    │  ◀── arip_core/correlator/
   TOR       │   │  JaegerClient       │    │
              │   │  DockerLogsClient   │    │
              │   │  TimelineBuilder    │    │
              │   └────────────────────┘    │
              │   spans + logs + db + tl   │
              └─────────────┬───────────────┘
                              │
                              ▼
              ┌────────────────────────────┐
   Phase 4   │   Hypotheses (ranked)       │
   ENGINE   │   ┌────────────────────┐    │  ◀── arip_core/engine/
              │   │  Rule (Protocol)    │    │
              │   │  ├ WebhookRace     │    │
              │   │  ├ DownstreamError │    │
              │   │  └ LatencyVsDB     │    │
              │   │  scoring (sev × c)  │    │
              │   └────────────────────┘    │
              └─────────────┬───────────────┘
                              │
                              ▼
              ┌────────────────────────────┐
   Phase 5   │   InvestigationReport       │
   REPORTER │   ┌────────────────────┐    │  ◀── arip_core/reporter/
              │   │  MarkdownWriter     │    │
              │   │  LLMSummarizer*    │    │
              │   └────────────────────┘    │
              │   reports/*.md + *.json    │
              └────────────────────────────┘

   * LLM is used **only** for the TL;DR; falls back to deterministic
     prose if no ANTHROPIC_API_KEY is set. Core analysis never touches it.
```

## Why these layers

- **Collector** is the only layer that knows about the test runner.
  Swap Playwright for pytest or a CI hook by writing one more parser
  that emits `FailureEvent`.
- **Correlator** is the only layer that knows about the telemetry
  backends. Today it speaks Jaeger HTTP and docker logs; tomorrow it
  speaks Tempo, Loki, k8s API, and Postgres slow-query log.
- **Engine** sees only normalised dataclasses. Rules are pure
  functions of `CorrelatedTelemetry`. They are deterministic.
- **Reporter** sees only the engine's findings. The LLM, if used,
  sees only the deterministic findings — never raw telemetry.

## What is intentionally NOT here

| Not built | Why |
|-----------|-----|
| Generic observability dashboard | Different product. |
| AI chatbot UI | Different product. |
| Self-healing test locator | Different product. |
| Remediation / auto-fix | Different product. |
| Jira / Slack integration | Out of MVP scope. |
| Broad connector ecosystem | Only what the demo stack needs. |
| Anomaly detection via LLM | Hypotheses must be deterministic and reproducible. |

## Data contracts (in one place)

- `FailureEvent` — `arip_core/collector/failure_event.py`
- `Span`, `LogEntry`, `DBQuery`, `K8sEvent`, `TimelineItem`, `CorrelatedTelemetry` — `arip_core/correlator/models.py`
- `Evidence`, `Hypothesis` — `arip_core/engine/models.py`
- `InvestigationReport` — `arip_core/reporter/models.py`

The dataclasses match the master prompt's spec one-for-one, with two
additions: `CorrelatedTelemetry.primary_trace_id` /
`related_trace_ids` / `order_id` (used to correlate the
two-trace `webhook_race` failure via the business key).

## End-to-end success criterion

> Playwright test fails → evidence-backed root-cause report in < 60s.

Measured: **6 seconds** in `bin/arip-e2e.sh` against the demo stack on
this laptop.
