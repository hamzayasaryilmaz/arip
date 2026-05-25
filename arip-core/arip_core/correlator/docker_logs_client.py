"""Read container logs via the local docker CLI.

This is the Phase 1/MVP substitute for a Loki/Elasticsearch client.
Both ARIP demo services emit structured JSON (slog), so parsing is
straightforward. The client API is intentionally narrow so a Loki
implementation can be dropped in by swapping the class behind a
shared protocol.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone

from .models import LogEntry

log = logging.getLogger(__name__)


class DockerLogsClient:
    def __init__(self, default_services: list[str] | None = None) -> None:
        self.default_services = default_services or [
            "arip-payment",
            "arip-inventory",
        ]

    def fetch(
        self,
        services: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        trace_ids: list[str] | None = None,
    ) -> list[LogEntry]:
        """Return JSON log lines from the given containers, optionally
        filtered by time range and trace_id."""
        services = services or self.default_services
        entries: list[LogEntry] = []
        for svc in services:
            entries.extend(self._read_container(svc, since, until))
        if trace_ids:
            wanted = set(trace_ids)
            entries = [e for e in entries if e.trace_id in wanted]
        entries.sort(key=lambda e: e.timestamp)
        return entries

    # --- internals ----------------------------------------------------

    def _read_container(
        self,
        container: str,
        since: datetime | None,
        until: datetime | None,
    ) -> list[LogEntry]:
        cmd = ["docker", "logs", "--timestamps"]
        if since:
            cmd += ["--since", _format_for_docker(since)]
        if until:
            cmd += ["--until", _format_for_docker(until)]
        cmd.append(container)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        except FileNotFoundError as exc:
            log.warning("docker CLI unavailable: %s", exc)
            return []
        if proc.returncode != 0:
            log.warning("docker logs %s failed: %s", container, proc.stderr.strip())
            return []
        return list(self._parse(container, proc.stdout)) + list(self._parse(container, proc.stderr))

    @staticmethod
    def _parse(container: str, raw: str):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Docker prepends an RFC3339Nano timestamp, then a space, then the original line.
            ts_str, _, rest = line.partition(" ")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.now(tz=timezone.utc)
                rest = line
            # Try JSON (structured slog) first; fall back to raw text.
            data: dict
            try:
                data = json.loads(rest)
            except json.JSONDecodeError:
                yield LogEntry(
                    timestamp=ts,
                    service_name=container.removeprefix("arip-"),
                    level="INFO",
                    message=rest,
                    trace_id=None,
                    fields={},
                )
                continue
            yield LogEntry(
                timestamp=ts,
                service_name=container.removeprefix("arip-"),
                level=str(data.get("level", "INFO")),
                message=str(data.get("msg", "")),
                trace_id=data.get("trace_id"),
                fields={k: v for k, v in data.items() if k not in {"time", "level", "msg"}},
            )


def _format_for_docker(dt: datetime) -> str:
    # docker logs --since accepts RFC3339 or unix timestamp; we use unix
    # to sidestep timezone parsing differences.
    return str(int(dt.timestamp()))
