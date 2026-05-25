"""Lightweight flaky-test classification.

A test is *flaky* if, over its recent history, it fails sometimes and
passes sometimes for the same input. We classify on a simple rule:

  * Need at least N runs to make a call (otherwise: ``unknown``).
  * fail_rate in [LOWER, UPPER]  →  ``flaky``
  * fail_rate >= UPPER           →  ``genuine`` (consistently broken)
  * fail_rate <= LOWER           →  ``genuine`` (consistently passing,
                                     this run is the new datapoint)

Tuned conservatively so we under-flag rather than mark real bugs flaky.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_RUNS_FOR_VERDICT = 5
FLAKY_LOWER_RATE = 0.05
FLAKY_UPPER_RATE = 0.95


@dataclass(frozen=True)
class FlakyVerdict:
    runs_considered: int
    fails: int
    fail_rate: float
    classification: str  # 'flaky' | 'genuine' | 'unknown'
    note: str


class FlakyClassifier:
    def classify(self, runs_considered: int, fails: int) -> FlakyVerdict:
        if runs_considered < MIN_RUNS_FOR_VERDICT:
            return FlakyVerdict(
                runs_considered=runs_considered,
                fails=fails,
                fail_rate=0.0 if runs_considered == 0 else fails / runs_considered,
                classification="unknown",
                note=(
                    f"Only {runs_considered} prior runs recorded; "
                    f"need at least {MIN_RUNS_FOR_VERDICT} to call flakiness."
                ),
            )
        rate = fails / runs_considered
        if FLAKY_LOWER_RATE < rate < FLAKY_UPPER_RATE:
            return FlakyVerdict(
                runs_considered=runs_considered,
                fails=fails,
                fail_rate=rate,
                classification="flaky",
                note=(
                    f"Failed {fails}/{runs_considered} runs ({rate:.0%}). "
                    "The test is non-deterministic on its own; investigate "
                    "but treat the failure as one data point, not a smoking gun."
                ),
            )
        return FlakyVerdict(
            runs_considered=runs_considered,
            fails=fails,
            fail_rate=rate,
            classification="genuine",
            note=(
                f"Failed {fails}/{runs_considered} runs ({rate:.0%}). "
                "The test is stable; this failure is unlikely to be flakiness."
            ),
        )
