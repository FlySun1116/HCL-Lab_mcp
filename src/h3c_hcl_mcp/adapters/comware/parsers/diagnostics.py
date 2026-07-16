"""Parse Comware ping and tracert output into bounded structured data.

The device output handled here is untrusted text.  These parsers only inspect
it with regular expressions; they never evaluate it or use it to construct a
command.  A malformed or incomplete response is returned as partial data with
``_parse_error`` instead of raising an exception.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from h3c_hcl_mcp.ports.command_parser import CommandParser

_PING_DESTINATION_RE = re.compile(
    r"^\s*ping\s+(?P<target>\S+?)(?:\s+\((?P<address>[^()\s]+)\))?\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_PING_STATISTICS_DESTINATION_RE = re.compile(
    r"^\s*-{2,}\s*(?:ping\s+statistics\s+for\s+)?(?P<target>\S+?)"
    r"(?:\s+ping\s+statistics)?\s*-{2,}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TRANSMITTED_RE = re.compile(r"(?P<count>\d+)\s+packet\(s\)\s+transmitted", re.IGNORECASE)
_RECEIVED_RE = re.compile(r"(?P<count>\d+)\s+packet\(s\)\s+received", re.IGNORECASE)
_LOSS_RE = re.compile(
    r"(?P<percent>\d+(?:\.\d+)?)\s*%\s+packet\s+loss",
    re.IGNORECASE,
)
_RTT_RE = re.compile(
    r"round-trip\s+min/avg/max(?:/[\w-]+)?\s*=\s*"
    r"(?P<minimum><?\d+(?:\.\d+)?)/"
    r"(?P<average><?\d+(?:\.\d+)?)/"
    r"(?P<maximum><?\d+(?:\.\d+)?)"
    r"(?:/<?\d+(?:\.\d+)?)?\s*ms",
    re.IGNORECASE,
)

_TRACE_DESTINATION_RE = re.compile(
    r"^\s*(?:trace(?:route|rt)|tracing\s+route)\s+to\s+"
    r"(?P<target>\S+?)(?:\s+\((?P<address>[^()\s]+)\))?"
    r"(?:\s*[,\r\n]|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
_HOP_LINE_RE = re.compile(r"^\s*(?P<index>\d+)\s+(?P<body>.*?)\s*$")
_RTT_VALUE_RE = re.compile(r"(?P<value><?\d+(?:\.\d+)?)\s*ms\b", re.IGNORECASE)
_HOST_AND_ADDRESS_RE = re.compile(r"^(?P<hostname>\S+)\s+\((?P<address>[^()\s]+)\)$")
_TRACE_COMPLETE_RE = re.compile(r"\b(?:trace(?:route|rt)\s+complete|trace\s+complete)\b", re.IGNORECASE)


def _command_name(command: str) -> str:
    """Return a normalized first command token without interpreting arguments."""

    parts = command.strip().casefold().split(maxsplit=1)
    return parts[0] if parts else ""


def _as_milliseconds(value: str) -> float:
    """Convert a Comware millisecond value to float.

    Comware can render very small values as ``<1``.  The exact measurement is
    unavailable, so the numeric upper bound (1.0) is retained rather than
    inventing a more precise value.
    """

    return float(value.removeprefix("<"))


def _summary_lines(raw_output: str) -> str:
    """Extract only ping statistics lines, preserving their untrusted text."""

    markers = ("packet(s) transmitted", "packet(s) received", "packet loss", "round-trip")
    lines: list[str] = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        folded = stripped.casefold()
        if stripped and any(marker in folded for marker in markers) and stripped not in lines:
            lines.append(stripped)
    return "\n".join(lines)


def _partial_error(missing: list[str], details: list[str] | None = None) -> str:
    """Build a stable, non-device-derived parse error message."""

    messages: list[str] = []
    if missing:
        messages.append(f"Missing fields: {', '.join(missing)}")
    if details:
        messages.extend(details)
    return "; ".join(messages) or "Incomplete diagnostic output"


class PingParser(CommandParser):
    """Parse typical English Comware 7 ``ping`` output."""

    def supports(self, model: str, version: str, command: str) -> bool:
        """Support the ping command for any Comware model or version."""

        return _command_name(command) == "ping"

    def parse(
        self,
        raw_output: str,
        model: str = "",
        version: str = "",
        command: str = "",
    ) -> dict[str, Any]:
        """Return ping counters, loss, RTT statistics, summary, and raw text."""

        result: dict[str, Any] = {
            "destination": None,
            "sent": None,
            "received": None,
            "loss_percent": None,
            "min_rtt_ms": None,
            "avg_rtt_ms": None,
            "max_rtt_ms": None,
            "summary": "",
            "raw": raw_output,
            "_raw": raw_output,
        }

        try:
            destination_match = _PING_DESTINATION_RE.search(raw_output)
            if destination_match:
                result["destination"] = destination_match.group("target")
            else:
                statistics_match = _PING_STATISTICS_DESTINATION_RE.search(raw_output)
                if statistics_match:
                    result["destination"] = statistics_match.group("target")

            transmitted_match = _TRANSMITTED_RE.search(raw_output)
            if transmitted_match:
                result["sent"] = int(transmitted_match.group("count"))

            received_match = _RECEIVED_RE.search(raw_output)
            if received_match:
                result["received"] = int(received_match.group("count"))

            loss_match = _LOSS_RE.search(raw_output)
            if loss_match:
                result["loss_percent"] = float(loss_match.group("percent"))
            elif result["sent"] is not None and result["received"] is not None:
                sent = result["sent"]
                received = result["received"]
                if sent > 0:
                    result["loss_percent"] = round((sent - received) * 100.0 / sent, 3)

            rtt_match = _RTT_RE.search(raw_output)
            if rtt_match:
                result["min_rtt_ms"] = _as_milliseconds(rtt_match.group("minimum"))
                result["avg_rtt_ms"] = _as_milliseconds(rtt_match.group("average"))
                result["max_rtt_ms"] = _as_milliseconds(rtt_match.group("maximum"))

            result["summary"] = _summary_lines(raw_output)

            missing = [
                field
                for field in ("destination", "sent", "received", "loss_percent")
                if result[field] is None
            ]
            if result["received"] not in (None, 0):
                missing.extend(
                    field for field in ("min_rtt_ms", "avg_rtt_ms", "max_rtt_ms") if result[field] is None
                )

            details: list[str] = []
            sent = result["sent"]
            received = result["received"]
            if sent is not None and received is not None and received > sent:
                details.append("Received count exceeds transmitted count")
            if missing or details:
                result["_parse_error"] = _partial_error(missing, details)
            return result
        except Exception:
            # Never include exception/device text in the stable parse error.
            result["_parse_error"] = "Failed to parse ping output"
            return result


class TracerouteParser(CommandParser):
    """Parse typical English Comware 7 ``tracert`` output."""

    def supports(self, model: str, version: str, command: str) -> bool:
        """Support only the Comware tracert command."""

        return _command_name(command) == "tracert"

    def parse(
        self,
        raw_output: str,
        model: str = "",
        version: str = "",
        command: str = "",
    ) -> dict[str, Any]:
        """Return destination, ordered hops, completion state, and raw text."""

        result: dict[str, Any] = {
            "destination": None,
            "hops": [],
            "completed": False,
            "raw": raw_output,
            "_raw": raw_output,
        }

        try:
            destination_match = _TRACE_DESTINATION_RE.search(raw_output)
            destination_address: str | None = None
            if destination_match:
                result["destination"] = destination_match.group("target")
                destination_address = destination_match.group("address")

            hops: list[dict[str, Any]] = []
            details: list[str] = []
            for line in raw_output.splitlines():
                hop_match = _HOP_LINE_RE.match(line)
                if not hop_match:
                    continue

                index = int(hop_match.group("index"))
                body = hop_match.group("body").strip()
                rtt_matches = list(_RTT_VALUE_RE.finditer(body))
                rtt_values = [_as_milliseconds(match.group("value")) for match in rtt_matches]
                has_timeout_marker = "*" in body

                prefix_end = len(body)
                if rtt_matches:
                    prefix_end = min(prefix_end, rtt_matches[0].start())
                star_position = body.find("*")
                if star_position >= 0:
                    prefix_end = min(prefix_end, star_position)
                identity = body[:prefix_end].strip()

                hostname: str | None = None
                address: str | None = None
                if identity:
                    host_and_address = _HOST_AND_ADDRESS_RE.match(identity)
                    if host_and_address:
                        hostname = host_and_address.group("hostname")
                        address = host_and_address.group("address")
                    elif _is_ip_address(identity):
                        address = identity
                    else:
                        hostname = identity

                if not rtt_values and not has_timeout_marker:
                    details.append(f"Hop {index} has no RTT or timeout marker")

                hops.append(
                    {
                        "index": index,
                        "address": address,
                        "hostname": hostname,
                        "rtt_ms": rtt_values,
                        "timeout": has_timeout_marker and not rtt_values,
                    }
                )

            result["hops"] = hops
            target_values = {
                value.casefold()
                for value in (result["destination"], destination_address)
                if isinstance(value, str) and value
            }
            reached_destination = any(
                value.casefold() in target_values
                for hop in hops
                for value in (hop["address"], hop["hostname"])
                if isinstance(value, str) and value
            )
            result["completed"] = reached_destination or bool(_TRACE_COMPLETE_RE.search(raw_output))

            missing: list[str] = []
            if result["destination"] is None:
                missing.append("destination")
            if not hops:
                missing.append("hops")
            if missing or details:
                result["_parse_error"] = _partial_error(missing, details)
            return result
        except Exception:
            # Never allow malformed device text to escape the parser as an exception.
            result["_parse_error"] = "Failed to parse tracert output"
            return result


def _is_ip_address(value: str) -> bool:
    """Return whether *value* is an IPv4 or IPv6 address."""

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


# Short command-oriented name for integrations that prefer Comware terminology.
TracertParser = TracerouteParser
