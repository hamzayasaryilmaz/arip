"""Normalized failure event produced when a test fails.

The shape of this event is the contract between the collector (Phase 2)
and every downstream stage (correlator, engine, reporter). Keep it
small, JSON-serialisable, and free of runner-specific fields.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class FailureEvent:
    """A test failure, normalised across runners."""

    test_name: str
    timestamp: datetime
    environment: str
    trace_id: str
    assertion: str
    error_message: str
    stack_trace: str | None = None
    test_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FailureEvent:
        ts = d["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return cls(
            test_name=d["test_name"],
            timestamp=ts,
            environment=d["environment"],
            trace_id=d["trace_id"],
            assertion=d["assertion"],
            error_message=d["error_message"],
            stack_trace=d.get("stack_trace"),
            test_metadata=d.get("test_metadata", {}),
        )

    @classmethod
    def load(cls, path: str | Path) -> FailureEvent:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json())
        return p
