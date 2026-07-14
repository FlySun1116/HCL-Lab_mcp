"""Parse 'display version' output into device facts."""

from __future__ import annotations

import re
from typing import Any

from h3c_hcl_mcp.ports.command_parser import CommandParser

# Patterns for extracting fields from display version output
_SYSNAME_RE = re.compile(r"^\s*(\S+)\s+uptime\s+is\s+", re.MULTILINE)
_VERSION_RE = re.compile(
    r"Comware\s+Software,\s*Version\s+([\d.]+)\s*,?\s*Release\s+(\S+)",
    re.IGNORECASE,
)
_UPTIME_RE = re.compile(r"uptime\s+is\s+(.+)$", re.MULTILINE)
_MODEL_LINE_RE = re.compile(r"^(H3C\s+)?(\S+(?:-\S+)*)\s*$", re.MULTILINE)
_MEMORY_RE = re.compile(r"(\d+[GMK])\s*Memory", re.IGNORECASE)
_FLASH_RE = re.compile(r"(\d+[GMK])\s*Flash", re.IGNORECASE)
_SERIAL_RE = re.compile(r"Board\s+ID\s*:\s*(\S+)", re.IGNORECASE)
_REBOOT_RE = re.compile(r"Last\s+reboot\s+reason\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


class FactsParser(CommandParser):
    """Parse 'display version' output into device facts.

    Extracts: sysname, comware_version, comware_release, uptime,
    model, memory, flash, serial, last_reboot_reason.
    """

    def supports(self, model: str, version: str, command: str) -> bool:
        """FactsParser handles 'display version' for all Comware devices."""
        return "display version" in command.lower()

    def parse(
        self,
        raw_output: str,
        model: str = "",
        version: str = "",
        command: str = "",
    ) -> dict[str, Any]:
        """Parse display version output into structured facts.

        Args:
            raw_output: Raw CLI output from 'display version'.
            model: Device model hint (unused; parsed from output).
            version: Comware version hint (unused; parsed from output).
            command: The command that produced this output.

        Returns:
            Dict with parsed facts plus _raw on success, or _raw + _parse_error on failure.
        """
        try:
            facts: dict[str, Any] = {}

            # Sysname — the word right before "uptime is"
            m = _SYSNAME_RE.search(raw_output)
            if m:
                facts["sysname"] = m.group(1).strip()

            # Comware version and release
            m = _VERSION_RE.search(raw_output)
            if m:
                facts["comware_version"] = m.group(1)
                facts["comware_release"] = m.group(2)

            # Uptime
            m = _UPTIME_RE.search(raw_output)
            if m:
                facts["uptime"] = m.group(1).strip()

            # Last reboot reason
            m = _REBOOT_RE.search(raw_output)
            if m:
                facts["last_reboot_reason"] = m.group(1).strip()

            # Memory
            m = _MEMORY_RE.search(raw_output)
            if m:
                facts["memory"] = m.group(1)

            # Flash
            m = _FLASH_RE.search(raw_output)
            if m:
                facts["flash"] = m.group(1)

            # Board ID / Serial
            m = _SERIAL_RE.search(raw_output)
            if m:
                facts["serial"] = m.group(1)

            # Model — try to extract from the hardware description lines
            # Look for known model patterns after the copyright block
            facts["model"] = model or _extract_model(raw_output)

            facts["_raw"] = raw_output
            return facts

        except Exception as exc:
            return {
                "_raw": raw_output,
                "_parse_error": str(exc),
            }


def _extract_model(raw_output: str) -> str | None:
    """Heuristic to extract the device model from display version output.

    Looks for hardware model identifiers like S6850, MSR36-20, etc.
    after the copyright banner.
    """
    lines = raw_output.splitlines()
    copyright_seen = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if "copyright" in stripped.lower():
            copyright_seen = True
            continue
        if copyright_seen and not stripped.startswith(("MPU", "Board", "Memory", "Flash")):
            # Look for model patterns
            # Common Comware models: H3C S6850, MSR36-20, S5130-28P-EI, etc.
            m = _MODEL_LINE_RE.match(stripped)
            if m:
                candidate = m.group(2)
                if candidate and not candidate.isdigit() and candidate.lower() != "comware":
                    return candidate
    return None
