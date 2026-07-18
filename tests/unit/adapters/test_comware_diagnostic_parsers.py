"""Synthetic unit tests for Comware ping and tracert parsers."""

from __future__ import annotations

import pytest

from h3c_hcl_mcp.adapters.comware.parsers.diagnostics import (
    PingParser,
    TracerouteParser,
)
from h3c_hcl_mcp.ports.command_parser import CommandParser

PING_SUCCESS = """\
<Router>ping -c 5 192.0.2.10
  Ping 192.0.2.10 (192.0.2.10): 56 data bytes, press CTRL_C to break
    56 bytes from 192.0.2.10: icmp_seq=0 ttl=255 time=1.000 ms
    56 bytes from 192.0.2.10: icmp_seq=1 ttl=255 time=2.000 ms
    56 bytes from 192.0.2.10: icmp_seq=2 ttl=255 time=1.000 ms
    56 bytes from 192.0.2.10: icmp_seq=3 ttl=255 time=3.000 ms
    56 bytes from 192.0.2.10: icmp_seq=4 ttl=255 time=2.000 ms

  --- Ping statistics for 192.0.2.10 ---
    5 packet(s) transmitted, 5 packet(s) received, 0.0% packet loss
    round-trip min/avg/max/std-dev = 1.000/1.800/3.000/0.748 ms
<Router>
"""

PING_TOTAL_LOSS = """\
  Ping 198.51.100.9 (198.51.100.9): 56 data bytes, press CTRL_C to break

  --- Ping statistics for 198.51.100.9 ---
    4 packet(s) transmitted, 0 packet(s) received, 100.00% packet loss
"""

PING_PARTIAL_LOSS = """\
  Ping edge.example (203.0.113.8): 56 data bytes, press CTRL_C to break
    56 bytes from 203.0.113.8: icmp_seq=0 ttl=62 time=<1 ms
    56 bytes from 203.0.113.8: icmp_seq=2 ttl=62 time=2 ms

  --- edge.example ping statistics ---
    5 packet(s) transmitted
    2 packet(s) received
    60% packet loss
    round-trip min/avg/max = <1/1.5/2 ms
"""

TRACERT_SUCCESS = """\
<Router>tracert -m 30 203.0.113.9
 traceroute to 203.0.113.9 (203.0.113.9), 30 hops at most, 40 bytes each packet,
 press CTRL_C to break

  1  192.0.2.1  1.000 ms  2.000 ms  1.000 ms
  2  198.51.100.1  5.000 ms  4.000 ms  6.000 ms
  3  203.0.113.9  9.000 ms  8.000 ms  9.000 ms
<Router>
"""

TRACERT_HOSTNAME_AND_TIMEOUT = """\
 traceroute to service.example (203.0.113.77), 30 hops at most, 40 bytes each packet
  1  gateway.example (192.0.2.1)  1 ms  1.5 ms  2 ms
  2  *  *  *
  3  transit.example (198.51.100.4)  8 ms  *  9 ms
  4  service.example (203.0.113.77)  12 ms  11 ms  12 ms
"""


class TestPingParser:
    """Ping parser behavior for complete, lossy, and damaged output."""

    @pytest.fixture
    def parser(self) -> PingParser:
        return PingParser()

    def test_implements_command_parser(self, parser: PingParser) -> None:
        assert isinstance(parser, CommandParser)

    @pytest.mark.parametrize(
        "command",
        ["ping", "PING", "  ping -c 5 192.0.2.10  "],
    )
    def test_supports_ping_commands(self, parser: PingParser, command: str) -> None:
        assert parser.supports("S6850", "7.1.070", command) is True

    @pytest.mark.parametrize("command", ["", "display ping", "tracert 192.0.2.10"])
    def test_rejects_other_commands(self, parser: PingParser, command: str) -> None:
        assert parser.supports("", "", command) is False

    def test_parses_successful_ping(self, parser: PingParser) -> None:
        result = parser.parse(PING_SUCCESS, command="ping")

        assert result["destination"] == "192.0.2.10"
        assert result["sent"] == 5
        assert result["received"] == 5
        assert result["loss_percent"] == 0.0
        assert result["min_rtt_ms"] == 1.0
        assert result["avg_rtt_ms"] == 1.8
        assert result["max_rtt_ms"] == 3.0
        assert "5 packet(s) transmitted" in result["summary"]
        assert "round-trip min/avg/max/std-dev" in result["summary"]
        assert result["raw"] is PING_SUCCESS
        assert result["_raw"] is PING_SUCCESS
        assert "_parse_error" not in result

    def test_parses_one_hundred_percent_loss_without_requiring_rtt(self, parser: PingParser) -> None:
        result = parser.parse(PING_TOTAL_LOSS)

        assert result["destination"] == "198.51.100.9"
        assert result["sent"] == 4
        assert result["received"] == 0
        assert result["loss_percent"] == 100.0
        assert result["min_rtt_ms"] is None
        assert result["avg_rtt_ms"] is None
        assert result["max_rtt_ms"] is None
        assert "_parse_error" not in result

    def test_parses_partial_loss_hostname_and_less_than_rtt(self, parser: PingParser) -> None:
        result = parser.parse(PING_PARTIAL_LOSS)

        assert result["destination"] == "edge.example"
        assert result["sent"] == 5
        assert result["received"] == 2
        assert result["loss_percent"] == 60.0
        assert result["min_rtt_ms"] == 1.0
        assert result["avg_rtt_ms"] == 1.5
        assert result["max_rtt_ms"] == 2.0
        assert "_parse_error" not in result

    def test_derives_loss_when_device_omits_loss_field(self, parser: PingParser) -> None:
        raw = """\
Ping 192.0.2.20 (192.0.2.20): 56 data bytes
4 packet(s) transmitted, 3 packet(s) received
round-trip min/avg/max = 1/2/4 ms
"""
        result = parser.parse(raw)

        assert result["loss_percent"] == 25.0
        assert "_parse_error" not in result

    def test_returns_partial_fields_and_error_for_damaged_statistics(self, parser: PingParser) -> None:
        raw = """\
Ping 192.0.2.30 (192.0.2.30): 56 data bytes
5 packet(s) transmitted
untrusted device text instead of the remaining statistics
"""
        result = parser.parse(raw)

        assert result["destination"] == "192.0.2.30"
        assert result["sent"] == 5
        assert result["received"] is None
        assert result["loss_percent"] is None
        assert "received" in result["_parse_error"]
        assert result["raw"] == raw

    def test_empty_output_is_a_structured_parse_error(self, parser: PingParser) -> None:
        result = parser.parse("")

        assert result["destination"] is None
        assert result["sent"] is None
        assert result["summary"] == ""
        assert "_parse_error" in result

    def test_inconsistent_counts_are_reported_without_raising(self, parser: PingParser) -> None:
        raw = """\
Ping 192.0.2.40 (192.0.2.40): 56 data bytes
1 packet(s) transmitted, 2 packet(s) received, 0% packet loss
round-trip min/avg/max = 1/1/1 ms
"""
        result = parser.parse(raw)

        assert result["sent"] == 1
        assert result["received"] == 2
        assert "Received count exceeds transmitted count" in result["_parse_error"]


class TestTracerouteParser:
    """Tracert parser behavior for destinations, hops, and timeouts."""

    @pytest.fixture
    def parser(self) -> TracerouteParser:
        return TracerouteParser()

    def test_implements_command_parser(self, parser: TracerouteParser) -> None:
        assert isinstance(parser, CommandParser)

    @pytest.mark.parametrize(
        "command",
        ["tracert", "TRACERT", " tracert -m 30 203.0.113.9 "],
    )
    def test_supports_tracert_commands(self, parser: TracerouteParser, command: str) -> None:
        assert parser.supports("S6850", "7.1.070", command) is True

    @pytest.mark.parametrize("command", ["", "traceroute 203.0.113.9", "ping 203.0.113.9"])
    def test_rejects_other_commands(self, parser: TracerouteParser, command: str) -> None:
        assert parser.supports("", "", command) is False

    def test_parses_completed_numeric_route(self, parser: TracerouteParser) -> None:
        result = parser.parse(TRACERT_SUCCESS, command="tracert")

        assert result["destination"] == "203.0.113.9"
        assert result["completed"] is True
        assert len(result["hops"]) == 3
        assert result["hops"][0] == {
            "index": 1,
            "address": "192.0.2.1",
            "hostname": None,
            "rtt_ms": [1.0, 2.0, 1.0],
            "timeout": False,
        }
        assert result["hops"][-1]["address"] == "203.0.113.9"
        assert result["raw"] is TRACERT_SUCCESS
        assert result["_raw"] is TRACERT_SUCCESS
        assert "_parse_error" not in result

    def test_parses_star_hop_hostname_and_ip(self, parser: TracerouteParser) -> None:
        result = parser.parse(TRACERT_HOSTNAME_AND_TIMEOUT)

        assert result["destination"] == "service.example"
        assert result["completed"] is True
        assert result["hops"][0]["hostname"] == "gateway.example"
        assert result["hops"][0]["address"] == "192.0.2.1"
        assert result["hops"][1] == {
            "index": 2,
            "address": None,
            "hostname": None,
            "rtt_ms": [],
            "timeout": True,
        }
        assert result["hops"][2]["hostname"] == "transit.example"
        assert result["hops"][2]["address"] == "198.51.100.4"
        assert result["hops"][2]["rtt_ms"] == [8.0, 9.0]
        assert result["hops"][2]["timeout"] is False
        assert "_parse_error" not in result

    def test_route_without_destination_hop_is_incomplete(self, parser: TracerouteParser) -> None:
        raw = """\
traceroute to 203.0.113.90 (203.0.113.90), 3 hops at most
1  192.0.2.1  1 ms  1 ms  1 ms
2  * * *
3  198.51.100.1  10 ms  10 ms  11 ms
"""
        result = parser.parse(raw)

        assert result["completed"] is False
        assert len(result["hops"]) == 3
        assert "_parse_error" not in result

    def test_explicit_completion_marker_is_honored(self, parser: TracerouteParser) -> None:
        raw = """\
Tracing route to service.example (203.0.113.91), 30 hops at most
1  gateway.example (192.0.2.1)  1 ms  1 ms  1 ms
Trace complete.
"""
        result = parser.parse(raw)

        assert result["destination"] == "service.example"
        assert result["completed"] is True

    def test_returns_partial_hop_and_error_for_malformed_hop(self, parser: TracerouteParser) -> None:
        raw = """\
traceroute to 203.0.113.92 (203.0.113.92), 30 hops at most
1  192.0.2.1  response format damaged
"""
        result = parser.parse(raw)

        assert result["destination"] == "203.0.113.92"
        assert result["hops"][0]["address"] is None
        assert result["hops"][0]["hostname"] == "192.0.2.1  response format damaged"
        assert result["hops"][0]["rtt_ms"] == []
        assert "Hop 1 has no RTT or timeout marker" in result["_parse_error"]
        assert result["completed"] is False

    def test_garbage_output_is_a_structured_parse_error(self, parser: TracerouteParser) -> None:
        raw = "untrusted device text without a destination or hop table"
        result = parser.parse(raw)

        assert result["destination"] is None
        assert result["hops"] == []
        assert result["completed"] is False
        assert "destination" in result["_parse_error"]
        assert "hops" in result["_parse_error"]
        assert result["raw"] == raw
