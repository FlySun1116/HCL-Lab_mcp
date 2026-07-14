"""Parse 'display interface brief' output into structured interface data."""

from __future__ import annotations

import re
from typing import Any

from h3c_hcl_mcp.ports.command_parser import CommandParser

# Regex for a single interface row in display interface brief output.
# Format: InterfaceName  LinkStatus  Speed  Description
# Examples:
#   GE1/0/1              UP     1G         Uplink to Core
#   LoopBack0            UP     -          Management Loopback
#   XGE1/0/1             DOWN   auto
_IFACE_ROW_RE = re.compile(
    r"^(\S+)\s+(UP|DOWN|ADM(?:IN)?|UP\s*\(\S+\))\s+(\S+)\s*(.*?)$",
    re.IGNORECASE,
)

# Header line indicating start of the interface table
_HEADER_RE = re.compile(r"^Interface\s+Link\s+Speed\s+Description", re.IGNORECASE)


class InterfaceBriefParser(CommandParser):
    """Parse 'display interface brief' output into a list of interface dicts.

    Each interface dict includes: name, status, speed, description.
    """

    def supports(self, model: str, version: str, command: str) -> bool:
        """InterfaceBriefParser handles 'display interface brief' for all Comware devices."""
        return "display interface brief" in command.lower()

    def parse(
        self,
        raw_output: str,
        model: str = "",
        version: str = "",
        command: str = "",
    ) -> dict[str, Any]:
        """Parse display interface brief output.

        Args:
            raw_output: Raw CLI output from 'display interface brief'.
            model: Device model (unused for this parser).
            version: Comware version (unused for this parser).
            command: The command that produced this output.

        Returns:
            Dict with 'interfaces' list plus _raw, or _raw + _parse_error on failure.
        """
        try:
            interfaces: list[dict[str, str]] = []
            header_found = False

            for line in raw_output.splitlines():
                stripped = line.strip()

                if not stripped:
                    continue

                # Detect the header line
                if _HEADER_RE.search(stripped):
                    header_found = True
                    continue

                if not header_found:
                    continue

                # Try to parse as an interface row
                m = _IFACE_ROW_RE.match(stripped)
                if m:
                    name = m.group(1)
                    status_raw = m.group(2).upper()
                    speed = m.group(3)
                    description = m.group(4).strip() if m.group(4) else ""

                    # Normalize ADM -> DOWN (administratively down)
                    if status_raw.startswith("ADM"):
                        status_norm = "DOWN"
                    elif status_raw.startswith("UP"):
                        status_norm = "UP"
                    else:
                        status_norm = "DOWN"

                    interfaces.append(
                        {
                            "name": name,
                            "status": status_norm,
                            "speed": speed,
                            "description": description,
                        }
                    )

            if not interfaces:
                return {
                    "_raw": raw_output,
                    "_parse_error": "No interface rows found in output",
                    "interfaces": [],
                }

            return {
                "interfaces": interfaces,
                "_raw": raw_output,
            }

        except Exception as exc:
            return {
                "_raw": raw_output,
                "_parse_error": str(exc),
                "interfaces": [],
            }
