# Normalization configs

ARIP's investigation rules consume **canonical signals** — config-driven
abstractions over raw telemetry attribute names. Onboarding a new
environment means writing a YAML config in this directory; you do not
need to write or modify any rule.

## Files

- **[demo.yaml](demo.yaml)** — the ARIP demo stack's conventions. Also
  the built-in default; the CLI uses these when `--config` is omitted.
- **[foreign-conventions.yaml](foreign-conventions.yaml)** — a synthetic
  example showing that the same rules apply to telemetry that uses
  completely different attribute names (`tenant.id` instead of
  `order.id`, `http.retry.attempt_number` instead of `retry.attempt`,
  …). Used as a portability test.

## Usage

```bash
arip investigate <report.json> --config configs/foreign-conventions.yaml
```

## Schema

See [docs/ONBOARDING.md](../../docs/ONBOARDING.md) for the field-by-field
reference. The dataclass that backs this config is
[`arip_core.canonical.config.NormalizationConfig`](../arip_core/canonical/config.py).

## What you don't need to configure

If your telemetry uses the **standard OTel semantic conventions** for
HTTP status, DB system, and span errors, the default values will work.
You typically only need to set `business_keys`, `retry.*`, and
`state_transitions` to match your application-specific conventions.
