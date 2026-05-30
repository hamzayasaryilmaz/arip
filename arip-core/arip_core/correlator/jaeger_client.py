"""Jaeger HTTP API client.

Jaeger's UI exposes a small JSON API at ``/api/...`` which is sufficient
for our needs. We only depend on it via ``httpx`` so the client is easy
to swap for Tempo or OTLP/Collector later.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import Span

log = logging.getLogger(__name__)


class JaegerClient:
    def __init__(self, base_url: str = "http://localhost:16686", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JaegerClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- public API ---------------------------------------------------

    def get_trace(self, trace_id: str) -> list[Span]:
        """Return every span in the given trace, normalised to ``Span``.

        Returns an empty list when Jaeger does not yet know about the
        trace — this is normal when the SDK's batch processor has not
        flushed the span yet. Callers that *require* the trace can use
        :meth:`get_trace_with_retry`."""
        url = f"{self.base_url}/api/traces/{trace_id}"
        resp = self._client.get(url)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        payload = resp.json()
        spans: list[Span] = []
        for trace in payload.get("data", []):
            spans.extend(self._spans_from_trace(trace))
        return spans

    def get_trace_with_retry(
        self,
        trace_id: str,
        attempts: int = 6,
        interval_s: float = 1.0,
    ) -> list[Span]:
        """Like :meth:`get_trace` but polls until the trace shows up.

        The OTel SDK's BatchSpanProcessor flushes on its own schedule
        (every ~5s by default). Tests can complete and trigger
        investigation before the span has reached Jaeger; this method
        gives the backend a bounded amount of time to catch up."""
        import time as _t

        for i in range(attempts):
            spans = self.get_trace(trace_id)
            if spans:
                return spans
            if i + 1 < attempts:
                log.info("trace %s not yet in jaeger; retry %d/%d", trace_id, i + 1, attempts)
                _t.sleep(interval_s)
        return []

    def find_traces_by_tag(
        self,
        service: str,
        tag_key: str,
        tag_value: str,
        lookback_seconds: int = 600,
        limit: int = 20,
    ) -> list[str]:
        """Return trace IDs where ``service`` has a span tagged
        ``tag_key=tag_value``. Used to find sibling traces (e.g. the
        webhook trace) that share the same ``order.id``."""
        end_us = int(datetime.now(tz=UTC).timestamp() * 1_000_000)
        start_us = end_us - (lookback_seconds * 1_000_000)
        params = {
            "service": service,
            "tags": f'{{"{tag_key}":"{tag_value}"}}',
            "start": str(start_us),
            "end": str(end_us),
            "limit": str(limit),
            "lookback": "custom",
        }
        url = f"{self.base_url}/api/traces"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
        ids: list[str] = []
        for trace in payload.get("data", []) or []:
            tid = trace.get("traceID")
            if tid:
                ids.append(tid)
        return ids

    # --- internals ----------------------------------------------------

    def _spans_from_trace(self, trace: dict[str, Any]) -> list[Span]:
        processes = trace.get("processes", {})
        out: list[Span] = []
        for raw in trace.get("spans", []):
            svc = processes.get(raw.get("processID"), {}).get("serviceName", "?")
            tags = {tag["key"]: tag.get("value") for tag in raw.get("tags", [])}
            status = (
                "ERROR"
                if tags.get("otel.status_code") == "ERROR" or tags.get("error") is True
                else "OK"
            )
            status_message = tags.get("otel.status_description") or tags.get("error.message") or ""
            parent = None
            for ref in raw.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent = ref.get("spanID")
            events: list[dict[str, Any]] = []
            for ev in raw.get("logs", []):
                fields = {f["key"]: f.get("value") for f in ev.get("fields", [])}
                events.append(
                    {
                        "timestamp": _us_to_datetime(ev["timestamp"]),
                        "fields": fields,
                    }
                )
            out.append(
                Span(
                    trace_id=raw["traceID"],
                    span_id=raw["spanID"],
                    parent_span_id=parent,
                    service_name=svc,
                    operation_name=raw["operationName"],
                    start_time=_us_to_datetime(raw["startTime"]),
                    duration_us=raw["duration"],
                    status=status,
                    status_message=status_message,
                    attributes=tags,
                    events=events,
                )
            )
        return out


def _us_to_datetime(us: int) -> datetime:
    return datetime.fromtimestamp(us / 1_000_000, tz=UTC)
