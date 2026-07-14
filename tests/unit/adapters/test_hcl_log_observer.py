"""Tests for HCL log observer."""

from __future__ import annotations

from h3c_hcl_mcp.adapters.hcl.log_observer import (
    LogEventType,
    LogObserver,
    extract_endpoints_from_events,
    parse_log_line,
    parse_log_lines,
    parse_timestamp,
)
from h3c_hcl_mcp.domain.device import DiscoverySource, TransportType


class TestParseTimestamp:
    """Test timestamp parsing."""

    def test_valid_timestamp(self):
        dt = parse_timestamp("2024-01-15 12:30:45")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 12
        assert dt.minute == 30
        assert dt.second == 45

    def test_invalid_timestamp_returns_none(self):
        assert parse_timestamp("not a timestamp") is None

    def test_empty_timestamp_returns_none(self):
        assert parse_timestamp("") is None
        assert parse_timestamp(None) is None  # type: ignore


class TestParseLogLine:
    """Test parsing individual log lines."""

    def test_device_started(self):
        line = "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000"
        event = parse_log_line(line)
        assert event.event_type == LogEventType.DEVICE_STARTED
        assert event.device_name == "S6850_1"
        assert event.device_id == 1
        assert event.console_port == 5000
        assert event.timestamp is not None

    def test_device_stopped(self):
        line = "2024-01-15 12:30:00 Device S6850_1 (id=1) stopped"
        event = parse_log_line(line)
        assert event.event_type == LogEventType.DEVICE_STOPPED
        assert event.device_name == "S6850_1"
        assert event.device_id == 1

    def test_console_port_allocated(self):
        line = "2024-01-15 12:00:01 Console port 5001 allocated to device 2"
        event = parse_log_line(line)
        assert event.event_type == LogEventType.CONSOLE_PORT_ALLOCATED
        assert event.device_id == 2
        assert event.console_port == 5001

    def test_console_port_released(self):
        line = "2024-01-15 12:30:01 Console port 5001 released from device 2"
        event = parse_log_line(line)
        assert event.event_type == LogEventType.CONSOLE_PORT_RELEASED
        assert event.device_id == 2
        assert event.console_port == 5001

    def test_unknown_line(self):
        line = "This is some random log output"
        event = parse_log_line(line)
        assert event.event_type == LogEventType.UNKNOWN

    def test_empty_line(self):
        event = parse_log_line("")
        assert event.event_type == LogEventType.UNKNOWN


class TestParseLogLines:
    """Test parsing multiple log lines."""

    def test_parses_and_filters_unknown(self):
        lines = [
            "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
            "some random noise",
            "2024-01-15 12:00:01 Device MSR36_1 (id=2) started, console port: 5001",
        ]
        events = parse_log_lines(lines)
        assert len(events) == 2
        assert all(e.event_type == LogEventType.DEVICE_STARTED for e in events)

    def test_empty_lines(self):
        events = parse_log_lines([])
        assert len(events) == 0


class TestExtractEndpointsFromEvents:
    """Test extracting RuntimeEndpoints from log events."""

    def test_started_events_produce_endpoints(self):
        lines = [
            "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
            "2024-01-15 12:00:01 Device MSR36_1 (id=2) started, console port: 5001",
        ]
        events = parse_log_lines(lines)
        endpoints = extract_endpoints_from_events(events)

        assert 1 in endpoints
        assert 2 in endpoints
        assert endpoints[1][0].port == 5000
        assert endpoints[1][0].transport == TransportType.CONSOLE_TELNET
        assert endpoints[1][0].source == DiscoverySource.LOG
        assert endpoints[1][0].confidence == 0.9

    def test_stopped_device_removes_endpoint(self):
        lines = [
            "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
            "2024-01-15 12:30:00 Device S6850_1 (id=1) stopped",
        ]
        events = parse_log_lines(lines)
        endpoints = extract_endpoints_from_events(events)

        assert 1 not in endpoints

    def test_port_allocate_and_release(self):
        lines = [
            "2024-01-15 12:00:01 Console port 5000 allocated to device 3",
            "2024-01-15 12:30:01 Console port 5000 released from device 3",
        ]
        events = parse_log_lines(lines)
        endpoints = extract_endpoints_from_events(events)

        assert 3 not in endpoints

    def test_empty_events(self):
        endpoints = extract_endpoints_from_events([])
        assert len(endpoints) == 0


class TestLogObserver:
    """Test the LogObserver class."""

    def test_feed_line_started(self):
        observer = LogObserver()
        event = observer.feed_line("2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000")
        assert event.event_type == LogEventType.DEVICE_STARTED
        assert observer.event_count == 1

        ep = observer.get_endpoint(1)
        assert ep is not None
        assert ep.port == 5000

    def test_feed_line_unknown_ignored(self):
        observer = LogObserver()
        event = observer.feed_line("some random noise")
        assert event.event_type == LogEventType.UNKNOWN
        assert observer.event_count == 0

    def test_feed_lines_batch(self):
        observer = LogObserver()
        events = observer.feed_lines(
            [
                "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
                "2024-01-15 12:00:01 Device MSR36_1 (id=2) started, console port: 5001",
            ]
        )
        assert len(events) == 2
        assert observer.event_count == 2
        assert observer.get_endpoint(1) is not None
        assert observer.get_endpoint(2) is not None

    def test_get_all_endpoints(self):
        observer = LogObserver()
        observer.feed_lines(
            [
                "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
                "2024-01-15 12:00:01 Device MSR36_1 (id=2) started, console port: 5001",
            ]
        )

        all_eps = observer.get_all_endpoints()
        assert len(all_eps) == 2

    def test_clear_resets_state(self):
        observer = LogObserver()
        observer.feed_line("2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000")
        assert observer.event_count == 1

        observer.clear()
        assert observer.event_count == 0
        assert observer.get_endpoint(1) is None
        assert len(observer.get_all_endpoints()) == 0

    def test_stopped_device_removed(self):
        observer = LogObserver()
        observer.feed_lines(
            [
                "2024-01-15 12:00:00 Device S6850_1 (id=1) started, console port: 5000",
                "2024-01-15 12:30:00 Device S6850_1 (id=1) stopped",
            ]
        )

        assert observer.get_endpoint(1) is None
