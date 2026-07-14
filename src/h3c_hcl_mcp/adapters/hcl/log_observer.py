"""HCL log observer — parse HCL runtime logs for port and state discovery.

v0.1: Parses synthetic log data for testing. Real HCL log file monitoring
will be implemented for v0.1.0-beta when HCL 5.10.x integration is available.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from h3c_hcl_mcp.domain.device import DiscoverySource, RuntimeEndpoint, TransportType


class LogEventType(StrEnum):
    """Types of events extractable from HCL logs."""

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
        raw_line: str = "",
    ) -> None:
        self.event_type = event_type
        self.timestamp = timestamp
        self.device_name = device_name
        self.device_id = device_id
        self.console_port = console_port
        self.raw_line = raw_line

    def __repr__(self) -> str:
        return (
            f"LogEvent(type={self.event_type.value}, device={self.device_name!r}, port={self.console_port})"
        )


# ------------------------------------------------------------------
# v0.1 synthetic log patterns — extend for real HCL log format
# ------------------------------------------------------------------

# Matches: "2024-01-01 12:00:00 Device S6850_1 (id=1) started, console port: 5000"
_STARTED_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"Device\s+(?P<name>\S+)\s+\(id=(?P<id>\d+)\)\s+started,\s+"
    r"console port:\s+(?P<port>\d+)"
)

# Matches: "2024-01-01 12:00:00 Device S6850_1 (id=1) stopped"
_STOPPED_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"Device\s+(?P<name>\S+)\s+\(id=(?P<id>\d+)\)\s+stopped"
)

# Matches: "2024-01-01 12:00:00 Console port 5000 allocated to device 1"
_PORT_ALLOCATED_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"Console port\s+(?P<port>\d+)\s+allocated to device\s+(?P<id>\d+)"
)

# Matches: "2024-01-01 12:00:00 Console port 5000 released from device 1"
_PORT_RELEASED_PATTERN = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"Console port\s+(?P<port>\d+)\s+released from device\s+(?P<id>\d+)"
)

_PATTERNS: list[tuple[re.Pattern, LogEventType]] = [
    (_STARTED_PATTERN, LogEventType.DEVICE_STARTED),
    (_STOPPED_PATTERN, LogEventType.DEVICE_STOPPED),
    (_PORT_ALLOCATED_PATTERN, LogEventType.CONSOLE_PORT_ALLOCATED),
    (_PORT_RELEASED_PATTERN, LogEventType.CONSOLE_PORT_RELEASED),
]


def parse_timestamp(ts_str: str) -> datetime | None:
    """Parse a timestamp string into a UTC datetime."""
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def parse_log_line(line: str) -> LogEvent:
    """Parse a single HCL log line into a LogEvent.

    Returns a LogEvent with event_type=UNKNOWN if the line doesn't match
    any known pattern.
    """
    for pattern, event_type in _PATTERNS:
        match = pattern.search(line)
        if match:
            groups = match.groupdict()
            timestamp = parse_timestamp(groups.get("ts", ""))
            device_name = groups.get("name")
            device_id = int(groups["id"]) if groups.get("id") else None
            console_port = int(groups["port"]) if groups.get("port") else None

            return LogEvent(
                event_type=event_type,
                timestamp=timestamp,
                device_name=device_name,
                device_id=device_id,
                console_port=console_port,
                raw_line=line,
            )

    return LogEvent(event_type=LogEventType.UNKNOWN, raw_line=line)


def parse_log_lines(lines: list[str]) -> list[LogEvent]:
    """Parse multiple HCL log lines.

    Args:
        lines: List of raw log line strings.

    Returns:
        List of parsed LogEvent objects. UNKNOWN events are filtered out.
    """
    events = [parse_log_line(line) for line in lines]
    return [e for e in events if e.event_type != LogEventType.UNKNOWN]


def extract_endpoints_from_events(
    events: list[LogEvent],
    project_id: str | None = None,
) -> dict[int, list[RuntimeEndpoint]]:
    """Extract RuntimeEndpoint entries from a list of parsed log events.

    Builds a mapping from device_id to its discovered console endpoints.
    Only the latest state for each device is returned.

    Args:
        events: Parsed log events (chronological order assumed).
        project_id: Optional project ID for metadata (not used in v0.1).

    Returns:
        Dict mapping device_id to list of RuntimeEndpoint.
    """
    endpoints_by_device: dict[int, RuntimeEndpoint] = {}
    stopped_devices: set[int] = set()
    console_to_device: dict[int, int] = {}

    for event in events:
        if event.device_id is None:
            continue

        if event.event_type == LogEventType.DEVICE_STOPPED:
            stopped_devices.add(event.device_id)

        elif event.event_type == LogEventType.CONSOLE_PORT_ALLOCATED:
            if event.console_port is not None:
                console_to_device[event.console_port] = event.device_id

        elif event.event_type == LogEventType.CONSOLE_PORT_RELEASED:
            if event.console_port is not None:
                console_to_device.pop(event.console_port, None)

        elif event.event_type == LogEventType.DEVICE_STARTED and event.console_port is not None:
            endpoint = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=event.console_port,
                source=DiscoverySource.LOG,
                confidence=0.9,
                discovered_at=event.timestamp,
            )
            endpoints_by_device[event.device_id] = endpoint

    # Also apply port allocations that weren't directly tied to a start event
    for port, device_id in console_to_device.items():
        if device_id not in endpoints_by_device:
            endpoint = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=port,
                source=DiscoverySource.LOG,
                confidence=0.85,
                discovered_at=datetime.now(tz=UTC),
            )
            endpoints_by_device[device_id] = endpoint

    # Build result, excluding stopped devices
    result: dict[int, list[RuntimeEndpoint]] = {}
    for device_id, endpoint in endpoints_by_device.items():
        if device_id not in stopped_devices:
            result[device_id] = [endpoint]

    return result


class LogObserver:
    """Observes HCL log output for device state changes.

    v0.1: Parses lines provided directly (simulated log).
    Future: Monitors HCL log files in real time using tail or file watchers.
    """

    def __init__(self) -> None:
        self._events: list[LogEvent] = []
        self._endpoints: dict[int, list[RuntimeEndpoint]] = {}

    def feed_line(self, line: str) -> LogEvent:
        """Feed a single log line to the observer."""
        event = parse_log_line(line)
        if event.event_type != LogEventType.UNKNOWN:
            self._events.append(event)
            self._rebuild_state()
        return event

    def feed_lines(self, lines: list[str]) -> list[LogEvent]:
        """Feed multiple log lines to the observer."""
        events = parse_log_lines(lines)
        self._events.extend(events)
        self._rebuild_state()
        return events

    def _rebuild_state(self) -> None:
        """Rebuild endpoint state from all accumulated events."""
        self._endpoints = extract_endpoints_from_events(self._events)

    def get_endpoint(self, device_id: int) -> RuntimeEndpoint | None:
        """Get the discovered endpoint for a device."""
        eps = self._endpoints.get(device_id, [])
        return eps[0] if eps else None

    def get_all_endpoints(self) -> dict[int, list[RuntimeEndpoint]]:
        """Get all discovered device endpoints."""
        return dict(self._endpoints)

    def clear(self) -> None:
        """Clear all accumulated events and state."""
        self._events.clear()
        self._endpoints.clear()

    @property
    def event_count(self) -> int:
        return len(self._events)
