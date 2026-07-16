"""Tests for HCL log observer."""

from __future__ import annotations

import os

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

    def test_real_hcl_millisecond_timestamp(self):
        dt = parse_timestamp("2026-07-14 23:10:34,113")
        assert dt is not None
        assert dt.microsecond == 113000

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

    def test_real_hcl_project_bound(self):
        line = (
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_sample_real\hcl_sample_real.net"
        )
        event = parse_log_line(line)
        assert event.event_type == LogEventType.PROJECT_BOUND
        assert event.topology_alias == "topo1"
        assert event.project_id == "hcl_sample_real"
        assert event.project_path is not None

    def test_real_hcl_console_created(self):
        line = (
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device2, telnet_port:30002)"
        )
        event = parse_log_line(line)
        assert event.event_type == LogEventType.CONSOLE_CREATED
        assert event.topology_alias == "topo1"
        assert event.device_id == 2
        assert event.console_port == 30002

    def test_real_hcl_console_closed(self):
        line = (
            "2026-07-14 23:11:00,001 - HCL topo1 -  INFO: close telnet_server "
            r"strPipeName:\\.\pipe\topo1-device2, telnet_port:30002)"
        )
        event = parse_log_line(line)
        assert event.event_type == LogEventType.CONSOLE_CLOSED
        assert event.topology_alias == "topo1"
        assert event.device_id == 2
        assert event.console_port == 30002

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

    def test_real_events_are_project_scoped(self):
        lines = [
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_alpha\hcl_alpha.net",
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)",
        ]
        events = parse_log_lines(lines)

        alpha = extract_endpoints_from_events(events, project_id="hcl_alpha")
        beta = extract_endpoints_from_events(events, project_id="hcl_beta")

        assert alpha[1][0].port == 30001
        assert beta == {}

    def test_alias_rebind_invalidates_old_project_endpoints(self):
        lines = [
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_old\hcl_old.net",
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)",
            "2026-07-14 23:12:00,001 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\AppData\Local\Temp\hcl_new\hcl_new.net",
        ]
        events = parse_log_lines(lines)

        assert extract_endpoints_from_events(events, project_id="hcl_old") == {}

    def test_real_close_removes_candidate(self):
        lines = [
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_alpha\hcl_alpha.net",
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)",
            "2026-07-14 23:11:00,001 - HCL topo1 -  INFO: close telnet_server "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)",
        ]

        assert extract_endpoints_from_events(parse_log_lines(lines), project_id="hcl_alpha") == {}


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

    def test_load_files_orders_events_by_timestamp(self, tmp_path):
        newer_file = tmp_path / "HCL.log"
        older_file = tmp_path / "HCL.log.rotated"
        newer_file.write_text(
            "2026-07-14 23:11:00,001 - HCL topo1 -  INFO: close telnet_server "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)" + "\n",
            encoding="utf-8",
        )
        older_file.write_text(
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_alpha\hcl_alpha.net" + "\n"
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)" + "\n",
            encoding="utf-8",
        )

        observer = LogObserver()
        observer.load_files([str(newer_file), str(older_file)])

        assert observer.get_project_endpoint("hcl_alpha", 1) is None
        assert observer.is_device_closed("hcl_alpha", 1)

    def test_load_files_preserves_binding_and_current_event_from_bounded_snapshot(self, tmp_path):
        log_file = tmp_path / "HCL.log"
        binding = (
            "2026-07-14 23:10:34,113 - HCL topo1 -  INFO: Workspace 1205 --- "
            r"C:\Users\lab\HCL\Projects\hcl_alpha\hcl_alpha.net"
            "\n"
        )
        created = (
            "2026-07-14 23:10:45,001 - HCL topo1 -  INFO: create_telnet_server success "
            r"strPipeName:\\.\pipe\topo1-device1, telnet_port:30001)"
            "\n"
        )
        log_file.write_bytes(binding.encode() + (b"X" * 8192) + b"\n" + created.encode())

        observer = LogObserver()
        observer.load_files([str(log_file)], max_bytes_per_file=1024)

        endpoint = observer.get_project_endpoint("hcl_alpha", 1)
        assert endpoint is not None
        assert endpoint.port == 30001

    def test_load_files_limits_rotated_file_count(self, tmp_path):
        paths = []
        for device_id in range(1, 4):
            path = tmp_path / f"HCL.log.{device_id}"
            path.write_text(
                f"2024-01-15 12:00:0{device_id} Device S6850_{device_id} "
                f"(id={device_id}) started, console port: 500{device_id}\n",
                encoding="utf-8",
            )
            os.utime(path, (device_id, device_id))
            paths.append(str(path))

        observer = LogObserver()
        observer.load_files(paths, max_files=2)

        assert observer.get_endpoint(1) is None
        assert observer.get_endpoint(2) is not None
        assert observer.get_endpoint(3) is not None
