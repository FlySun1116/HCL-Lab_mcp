"""Port: CommandParser — parse raw Comware CLI output into structured data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CommandParser(ABC):
    """Parse raw device CLI output into structured domain objects.

    Each parser declares which (model, version, command) combinations it supports.
    Unknown or unparseable output is returned as raw text with a warning.
    """

    @abstractmethod
    def supports(self, model: str, version: str, command: str) -> bool:
        """Check whether this parser can handle the given combination."""
        ...

    @abstractmethod
    def parse(self, raw_output: str, model: str, version: str, command: str) -> dict[str, Any]:
        """Parse raw output into structured data.

        Args:
            raw_output: The raw CLI output from the device.
            model: Device model (e.g. 'S6850').
            version: Comware version string.
            command: The command that produced this output.

        Returns:
            Structured data dict. On parse failure, returns {"_raw": raw_output, "_parse_error": "..."}.

        Raises:
            DomainError(COMMAND_PARSE_ERROR): parsing failed catastrophically.
        """
        ...
