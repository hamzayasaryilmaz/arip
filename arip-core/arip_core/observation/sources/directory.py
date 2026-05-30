"""Directory-of-JSON-bundles source.

Each file in the directory is one trace bundle (same shape as a single
JSONL line). Files are read in sorted order; the cursor is the
*relative path* of the most recently processed file. New files appended
to the directory after the cursor's filename are picked up by the next
run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .base import TraceObservation
from .jsonl import _bundle_to_observation


class DirectoryTraceSource:
    def __init__(self, root: str | Path, glob: str = "*.json") -> None:
        self.root = Path(root)
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(self.root)
        self.glob = glob
        self.name = f"dir://{self.root.resolve()}#{glob}"

    def stream(self, *, cursor: str | None, budget: int) -> Iterator[TraceObservation]:
        files = sorted(self.root.glob(self.glob))
        # Cursor format: last successfully emitted relative path.
        # Resume from the file *after* it (or the first if cursor is None).
        start_after = cursor
        yielded = 0
        for f in files:
            rel = str(f.relative_to(self.root))
            if start_after is not None and rel <= start_after:
                continue
            try:
                bundle: Any = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                # Bad file: skip but advance cursor so we don't loop.
                yield TraceObservation(
                    source_name=self.name,
                    observation_id=f"badfile:{rel}",
                    trace_id="",
                    spans=[],
                    cursor_after=rel,
                )
                continue
            obs = _bundle_to_observation(
                bundle,
                source_name=self.name,
                line_start=0,
                line_end=0,
            )
            if obs is None:
                continue
            # Override cursor_after with the relative path.
            obs.cursor_after = rel
            yield obs
            yielded += 1
            if yielded >= budget:
                return
