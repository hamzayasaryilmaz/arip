"""Source protocol + the unit of ingestion.

A `TraceObservation` is what a source yields: enough span + log data
for the engine to run against a single trace. Each observation carries
its own cursor-after position so the caller can persist progress per
observation, not per batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Protocol

from ...correlator.models import LogEntry, Span


@dataclass
class TraceObservation:
    source_name: str
    observation_id: str
    trace_id: str
    spans: list[Span]
    logs: list[LogEntry] = field(default_factory=list)
    observed_at: datetime | None = None
    cursor_after: str = ""


class Source(Protocol):
    """Read-only stream over trace observations."""

    name: str

    def stream(
        self, *, cursor: str | None, budget: int
    ) -> Iterator[TraceObservation]:
        """Yield up to ``budget`` observations starting after ``cursor``.

        Implementations MUST be:
          - read-only (no mutation of backing store)
          - resumable (a fresh call with the cursor of the last yielded
            observation reproduces the next observation)
          - idempotent (replays of the same cursor yield the same
            observation_id for the same content)
        """
        ...  # pragma: no cover
