# pilot-archive/

Per-pilot session archives. Each subdirectory holds the verbatim
artefacts from one pilot run — what ARIP saw, what it said, what
the engineer said back, what we decided to do about it.

These are **committed to the repo, not gitignored.** They are the
calibration corpus that future rules and confidence formulas are
tuned against.

## Directory shape

```
pilot-archive/
├── README.md                  ← you are here
├── _template/                 ← copy this when starting a new pilot
│   ├── feedback.md
│   ├── outcome.md
│   ├── config.yaml
│   ├── telemetry-quality.json
│   ├── generated-report.md
│   ├── pr-comment.md
│   ├── spans.json
│   └── logs.json
└── <pilot-id>/                ← one directory per pilot, e.g. p001/, p002/
    └── ... same 8 files
```

## What goes into each file

| File                      | Source                                          |
|---------------------------|-------------------------------------------------|
| `feedback.md`             | Filled-in `docs/pilot-feedback-template.md`     |
| `outcome.md`              | Pilot-owner post-session review (Step 10 of runbook) |
| `config.yaml`             | The normalization config used (copy from `arip-core/configs/`) |
| `telemetry-quality.json`  | `quality` field extracted from the investigation JSON |
| `generated-report.md`     | The markdown report ARIP produced               |
| `pr-comment.md`           | The PR comment ARIP rendered                    |
| `spans.json`              | Anonymised trace from Jaeger/Tempo              |
| `logs.json`               | Anonymised service logs                         |

## Anonymisation contract

Before committing **anything** from a pilot, run it through the
anonymisation rules in
[docs/PILOT_RUNBOOK.md → Step 7](../docs/PILOT_RUNBOOK.md#step-7--telemetry-anonymisation).

The pilot-archive will eventually be used to build the public
calibration dataset; we cannot have business identifiers in it.

Two people must sign off:
- The pilot owner (you), in `outcome.md`
- An independent reviewer who has not worked with the pilot's data,
  also in `outcome.md`

## How to use this archive

The archive feeds three downstream artefacts:

- **[docs/TELEMETRY_PATHOLOGIES.md](../docs/TELEMETRY_PATHOLOGIES.md)** —
  every new telemetry-shape problem learned from a pilot is
  catalogued there.
- **[docs/PILOT_SYNTHESIS_TEMPLATE.md](../docs/PILOT_SYNTHESIS_TEMPLATE.md)** —
  after every 3 pilots, the archive is reviewed for recurring patterns.
- **`arip-core/tests/test_calibration_benchmark.py`** — a pilot's
  pathology may justify a new synthetic-fixture test (NOT a new rule).
  The test is the durable artefact; the pilot data is provenance.

## How not to use this archive

- Do **not** edit a pilot's archive after the post-pilot review is
  signed off. Frozen.
- Do **not** anonymise lazily. PII leaks here are repository-wide.
- Do **not** add fictional / synthesised "pilots" to pad the corpus.
- Do **not** copy a pilot's `feedback.md` into a doc as marketing
  quotes. The corpus is data, not testimonials.

## Status

```
Current pilots:  0
Synthesis runs:  0 (next one happens after pilot 3)
Pathologies:     0 catalogued (see TELEMETRY_PATHOLOGIES.md)
```
