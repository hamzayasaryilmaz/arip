"""Read-only ingestion sources for observation mode.

Every source is a generator over `TraceObservation` instances. Sources
never mutate their backing store — observation mode is strictly
read-only by contract.
"""

from .base import Source, TraceObservation
from .directory import DirectoryTraceSource
from .jsonl import JsonlTraceSource

__all__ = [
    "Source",
    "TraceObservation",
    "JsonlTraceSource",
    "DirectoryTraceSource",
]
