"""Read-only HCL 5.10.x log observation for console discovery.

The observer deliberately consumes only HCL's ordinary text logs.  It does
not connect to HCL's private control services.  A log-derived endpoint is a
candidate: runtime discovery must still probe it before exposing it as usable.
"""

from __future__ import annotations

import ntpath
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from h3c_hcl_mcp.domain.device import DiscoverySource, RuntimeEndpoint, TransportType

_DEFAULT_MAX_LOG_FILES = 16
_DEFAULT_MAX_LOG_BYTES_PER_FILE = 4 * 1024 * 1024
_LOG_HEAD_BYTES = 64 * 1024


class LogEventType(StrEnum):
    """Types of events extractable from HCL logs."""

    # Real HCL 5.10.x events.
    PROJECT_BOUND = "project_bound"
    CONSOLE_CREATED = "console_created"
    CONSOLE_CLOSED = "console_closed"

    # Backward-compatible synthetic events used by existing fixtures.
    DEVICE_STARTED = "device_started"
    DEVICE_STOPPED = "device_stopped"
    CONSOLE_PORT_ALLOCATED = "console_port_allocated"
    CONSOLE_PORT_RELEASED = "console_port_released"
    UNKNOWN = "unknown"


class LogEvent:
    """A parsed event from an HCL log line."""

    def __init__(
        self,
        event_type: LogEventType,
        timestamp: datetime | None = None,
        device_name: str | None = None,
        device_id: int | None = None,
        console_port: int | None = None,
        topology_alias: str | None = None,
        project_id: str | None = None,
        project_path: str | None = None,
        raw_line: str = "",
    ) -> None:
        self.event_type = event_type
        self.timestamp = timestamp
        self.device_name = device_name
        self.device_id = device_id
        self.console_port = console_port
        self.topology_alias = topology_alias
        self.project_id = project_id
        self.project_path = project_path
        self.raw_line = raw_line

    def __repr__(self) -> str:
        return (
            f"LogEvent(type={self.event_type.value}, project={self.project_id!r}, "
            f"alias={self.topology_alias!r}, device={self.device_name!r}, "
            f"port={self.console_port})"
        )


_TIMESTAMP = r"(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d{1,6})?)"

# Real HCL 5.10.3 examples (paths and names are sanitized in test fixtures):
#   ... HCL topo1 ... Workspace 1205 --- C:\...\project\project.net
#   ... create_telnet_server success strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)
_PROJECT_BOUND_PATTERN = re.compile(
    _TIMESTAMP
    + r"\s+-\s+HCL\s+(?P<alias>topo\d+)\s+-.*?Workspace\s+1205\s+---\s+"
    + r"(?P<path>.+?\.net)\s*$",
    re.IGNORECASE,
)
_REAL_CONSOLE_PATTERN = re.compile(
    _TIMESTAMP
    + r"\s+-\s+HCL\s+(?P<alias>topo\d+)\s+-.*?"
    + r"(?P<action>create_telnet_server\s+success|close\s+telnet_server|clear\s+telnet\s+success)"
    + r".*?strPipeName:.*?(?P<pipe_alias>topo\d+)-device(?P<id>\d+),\s*"
    + r"telnet_port:(?P<port>\d+)",
    re.IGNORECASE,
)

# Backward-compatible synthetic patterns.
_STARTED_PATTERN = re.compile(
    _TIMESTAMP
    + r"\s+Device\s+(?P<name>\S+)\s+\(id=(?P<id>\d+)\)\s+started,\s+"
    + r"console port:\s+(?P<port>\d+)"
)
_STOPPED_PATTERN = re.compile(_TIMESTAMP + r"\s+Device\s+(?P<name>\S+)\s+\(id=(?P<id>\d+)\)\s+stopped")
_PORT_ALLOCATED_PATTERN = re.compile(
    _TIMESTAMP + r"\s+Console port\s+(?P<port>\d+)\s+allocated to device\s+(?P<id>\d+)"
)
_PORT_RELEASED_PATTERN = re.compile(
    _TIMESTAMP + r"\s+Console port\s+(?P<port>\d+)\s+released from device\s+(?P<id>\d+)"
)

_SYNTHETIC_PATTERNS: list[tuple[re.Pattern[str], LogEventType]] = [
    (_STARTED_PATTERN, LogEventType.DEVICE_STARTED),
    (_STOPPED_PATTERN, LogEventType.DEVICE_STOPPED),
    (_PORT_ALLOCATED_PATTERN, LogEventType.CONSOLE_PORT_ALLOCATED),
    (_PORT_RELEASED_PATTERN, LogEventType.CONSOLE_PORT_RELEASED),
]


def parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an HCL timestamp into an aware datetime used for ordering."""
    for timestamp_format in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts_str, timestamp_format).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue
    return None


def _project_id_from_net_path(net_path: str) -> str | None:
    """Return the project ID encoded by an HCL ``.net`` filename."""
    filename = ntpath.basename(net_path.strip().strip('"'))
    project_id, extension = ntpath.splitext(filename)
    if extension.lower() != ".net" or not project_id:
        return None
    return project_id


def parse_log_line(line: str) -> LogEvent:
    """Parse one real or synthetic HCL log line."""
    project_match = _PROJECT_BOUND_PATTERN.search(line)
    if project_match:
        groups = project_match.groupdict()
        project_path = groups["path"].strip().strip('"')
        project_id = _project_id_from_net_path(project_path)
        if project_id:
            return LogEvent(
                event_type=LogEventType.PROJECT_BOUND,
                timestamp=parse_timestamp(groups["ts"]),
                topology_alias=groups["alias"].lower(),
                project_id=project_id,
                project_path=project_path,
                raw_line=line,
            )

    console_match = _REAL_CONSOLE_PATTERN.search(line)
    if console_match:
        groups = console_match.groupdict()
        alias = groups["alias"].lower()
        pipe_alias = groups["pipe_alias"].lower()
        # A mismatch is malformed/ambiguous and must never produce a candidate.
        if alias == pipe_alias:
            action = groups["action"].lower()
            event_type = (
                LogEventType.CONSOLE_CREATED
                if action.startswith("create_telnet_server")
                else LogEventType.CONSOLE_CLOSED
            )
            return LogEvent(
                event_type=event_type,
                timestamp=parse_timestamp(groups["ts"]),
                topology_alias=alias,
                device_id=int(groups["id"]),
                console_port=int(groups["port"]),
                raw_line=line,
            )

    for pattern, event_type in _SYNTHETIC_PATTERNS:
        match = pattern.search(line)
        if match:
            groups = match.groupdict()
            return LogEvent(
                event_type=event_type,
                timestamp=parse_timestamp(groups.get("ts", "")),
                device_name=groups.get("name"),
                device_id=int(groups["id"]) if groups.get("id") else None,
                console_port=int(groups["port"]) if groups.get("port") else None,
                raw_line=line,
            )

    return LogEvent(event_type=LogEventType.UNKNOWN, raw_line=line)


def parse_log_lines(lines: list[str]) -> list[LogEvent]:
    """Parse multiple lines, filtering unrecognized log noise."""
    events = [parse_log_line(line) for line in lines]
    return [event for event in events if event.event_type != LogEventType.UNKNOWN]


class _ObservedState:
    """Internal chronological state reconstructed from log events."""

    def __init__(self) -> None:
        self.project_endpoints: dict[str, dict[int, RuntimeEndpoint]] = {}
        self.closed_devices: dict[str, set[int]] = {}
        self.legacy_endpoints: dict[int, RuntimeEndpoint] = {}


def _endpoint_from_event(event: LogEvent, confidence: float = 0.9) -> RuntimeEndpoint:
    if event.console_port is None:
        raise ValueError("console event has no port")
    extra: dict[str, str] = {}
    if event.topology_alias:
        extra["topology_alias"] = event.topology_alias
    return RuntimeEndpoint(
        transport=TransportType.CONSOLE_TELNET,
        host="127.0.0.1",
        port=event.console_port,
        source=DiscoverySource.LOG,
        confidence=confidence,
        discovered_at=event.timestamp,
        extra=extra,
    )


def _reconstruct_state(events: list[LogEvent]) -> _ObservedState:
    state = _ObservedState()
    alias_to_project: dict[str, str] = {}
    active_by_alias: dict[tuple[str, int], RuntimeEndpoint] = {}
    allocated_legacy: dict[int, int] = {}
    stopped_legacy: set[int] = set()

    for event in events:
        if event.event_type == LogEventType.PROJECT_BOUND:
            if event.topology_alias is None or event.project_id is None:
                continue
            alias = event.topology_alias
            old_project = alias_to_project.get(alias)
            if old_project != event.project_id:
                # HCL reuses topo1/topo2.  Never carry endpoints across a
                # reassignment, even if device IDs and ports happen to match.
                for key in [key for key in active_by_alias if key[0] == alias]:
                    active_by_alias.pop(key, None)
            alias_to_project[alias] = event.project_id
            continue

        if event.event_type in (LogEventType.CONSOLE_CREATED, LogEventType.CONSOLE_CLOSED):
            if event.topology_alias is None or event.device_id is None:
                continue
            alias = event.topology_alias
            project_id = alias_to_project.get(alias)
            if project_id is None:
                # Without an explicit project binding, alias/device IDs are
                # ambiguous and must not be exposed.
                continue
            key = (alias, event.device_id)
            if event.event_type == LogEventType.CONSOLE_CREATED and event.console_port is not None:
                active_by_alias[key] = _endpoint_from_event(event)
                state.closed_devices.setdefault(project_id, set()).discard(event.device_id)
            else:
                active_by_alias.pop(key, None)
                state.closed_devices.setdefault(project_id, set()).add(event.device_id)
            continue

        # Legacy synthetic state is intentionally unscoped for compatibility.
        if event.device_id is None:
            continue
        if event.event_type == LogEventType.DEVICE_STARTED and event.console_port is not None:
            state.legacy_endpoints[event.device_id] = _endpoint_from_event(event)
            stopped_legacy.discard(event.device_id)
        elif event.event_type == LogEventType.DEVICE_STOPPED:
            state.legacy_endpoints.pop(event.device_id, None)
            stopped_legacy.add(event.device_id)
        elif event.event_type == LogEventType.CONSOLE_PORT_ALLOCATED and event.console_port is not None:
            allocated_legacy[event.console_port] = event.device_id
            stopped_legacy.discard(event.device_id)
        elif event.event_type == LogEventType.CONSOLE_PORT_RELEASED and event.console_port is not None:
            allocated_legacy.pop(event.console_port, None)
            state.legacy_endpoints.pop(event.device_id, None)

    # Materialize only aliases that still point at the same project.
    for (alias, device_id), endpoint in active_by_alias.items():
        project_id = alias_to_project.get(alias)
        if project_id is not None:
            state.project_endpoints.setdefault(project_id, {})[device_id] = endpoint

    for port, device_id in allocated_legacy.items():
        if device_id not in state.legacy_endpoints and device_id not in stopped_legacy:
            state.legacy_endpoints[device_id] = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=port,
                source=DiscoverySource.LOG,
                confidence=0.85,
                discovered_at=None,
            )

    return state


def extract_endpoints_from_events(
    events: list[LogEvent],
    project_id: str | None = None,
) -> dict[int, list[RuntimeEndpoint]]:
    """Return current log-derived candidates after chronological reduction.

    Real HCL endpoints are project-scoped.  The unscoped form remains for the
    original synthetic fixtures and merges currently active real projects only
    for backward compatibility.
    """
    state = _reconstruct_state(events)
    if project_id is not None:
        return {
            device_id: [endpoint]
            for device_id, endpoint in state.project_endpoints.get(project_id, {}).items()
        }

    merged = dict(state.legacy_endpoints)
    for endpoints in state.project_endpoints.values():
        merged.update(endpoints)
    return {device_id: [endpoint] for device_id, endpoint in merged.items()}


def _read_bounded_log_lines(path: Path, max_bytes: int) -> list[str]:
    """Read a bounded head/tail snapshot without retaining partial lines."""
    with path.open("rb") as log_file:
        size = log_file.seek(0, 2)
        log_file.seek(0)
        if size <= max_bytes:
            payload = log_file.read(max_bytes)
        else:
            head_budget = min(_LOG_HEAD_BYTES, max_bytes // 4)
            tail_budget = max_bytes - head_budget

            head = log_file.read(head_budget)
            last_head_newline = max(head.rfind(b"\n"), head.rfind(b"\r"))
            head = head[: last_head_newline + 1] if last_head_newline >= 0 else b""

            log_file.seek(size - tail_budget)
            tail = log_file.read(tail_budget)
            first_tail_newline = tail.find(b"\n")
            tail = tail[first_tail_newline + 1 :] if first_tail_newline >= 0 else b""
            payload = head + tail

    return payload.decode("utf-8", errors="replace").splitlines()


class LogObserver:
    """Chronologically reconstruct HCL project/console state from text logs."""

    def __init__(self) -> None:
        self._events: list[LogEvent] = []
        self._state = _ObservedState()

    def feed_line(self, line: str) -> LogEvent:
        event = parse_log_line(line)
        if event.event_type != LogEventType.UNKNOWN:
            self._events.append(event)
            self._rebuild_state()
        return event

    def feed_lines(self, lines: list[str]) -> list[LogEvent]:
        events = parse_log_lines(lines)
        self._events.extend(events)
        self._rebuild_state()
        return events

    def load_files(
        self,
        paths: list[str],
        *,
        max_files: int = _DEFAULT_MAX_LOG_FILES,
        max_bytes_per_file: int = _DEFAULT_MAX_LOG_BYTES_PER_FILE,
    ) -> list[LogEvent]:
        """Load rotated/current HCL log files and order events by timestamp.

        File names and modification times are not reliable rotation order in
        HCL 5.10.x, so timestamps embedded in recognized lines are authoritative.
        Unreadable files are ignored and never create endpoints. Resource use
        is bounded by reading at most ``max_files`` and a head/tail window from
        each file; the head preserves initial project binding while the tail
        captures the current console state.
        """
        indexed_events: list[tuple[int, LogEvent]] = []
        sequence = 0
        candidates: list[tuple[int, int, Path]] = []
        for index, raw_path in enumerate(paths):
            path = Path(raw_path)
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file():
                candidates.append((stat.st_mtime_ns, index, path))

        selected = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[: max(1, max_files)]
        for _, _, path in selected:
            try:
                lines = _read_bounded_log_lines(path, max(256, max_bytes_per_file))
            except OSError:
                continue
            for event in parse_log_lines(lines):
                indexed_events.append((sequence, event))
                sequence += 1

        minimum = datetime.min.replace(tzinfo=UTC)
        indexed_events.sort(key=lambda item: (item[1].timestamp or minimum, item[0]))
        self._events = [event for _, event in indexed_events]
        self._rebuild_state()
        return list(self._events)

    def _rebuild_state(self) -> None:
        self._state = _reconstruct_state(self._events)

    def get_endpoint(self, device_id: int, project_id: str | None = None) -> RuntimeEndpoint | None:
        if project_id is not None:
            return self.get_project_endpoint(project_id, device_id)
        endpoint = self._state.legacy_endpoints.get(device_id)
        if endpoint is not None:
            return endpoint
        for project_endpoints in self._state.project_endpoints.values():
            endpoint = project_endpoints.get(device_id)
            if endpoint is not None:
                return endpoint
        return None

    def get_project_endpoint(self, project_id: str, device_id: int) -> RuntimeEndpoint | None:
        return self._state.project_endpoints.get(project_id, {}).get(device_id)

    def get_project_endpoints(self, project_id: str) -> dict[int, list[RuntimeEndpoint]]:
        return {
            device_id: [endpoint]
            for device_id, endpoint in self._state.project_endpoints.get(project_id, {}).items()
        }

    def is_device_closed(self, project_id: str, device_id: int) -> bool:
        return device_id in self._state.closed_devices.get(project_id, set())

    def get_all_endpoints(self) -> dict[int, list[RuntimeEndpoint]]:
        return extract_endpoints_from_events(self._events)

    def clear(self) -> None:
        self._events.clear()
        self._state = _ObservedState()

    @property
    def event_count(self) -> int:
        return len(self._events)
