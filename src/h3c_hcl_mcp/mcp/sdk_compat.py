"""Narrow compatibility boundary for MCP Python SDK 1.28 internals."""

from __future__ import annotations

from importlib.metadata import version as distribution_version
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import Server as LowLevelServer

VERIFIED_MCP_VERSION = "1.28.1"
_SUPPORTED_MCP_LINE = (1, 28)


def set_fastmcp_server_version(server: FastMCP[Any], server_version: str) -> None:
    """Set ``serverInfo.version`` behind one fail-fast SDK compatibility guard.

    FastMCP 1.28 does not expose a public version constructor or property.  Its
    low-level ``Server`` does, so this is the sole project access to the private
    bridge.  The dependency remains capped below MCP 1.29 until an upstream
    public FastMCP version API or a revalidated adapter is available.
    """

    installed = distribution_version("mcp")
    if _release_line(installed) != _SUPPORTED_MCP_LINE:
        raise RuntimeError(
            "Unsupported MCP Python SDK "
            f"{installed}; FastMCP compatibility was verified with {VERIFIED_MCP_VERSION} "
            "and is limited to the 1.28.x line."
        )

    low_level = getattr(server, "_mcp_server", None)
    if not isinstance(low_level, LowLevelServer) or not hasattr(low_level, "version"):
        raise RuntimeError(
            "MCP Python SDK 1.28 FastMCP structure is incompatible: "
            "expected a low-level Server with a version attribute."
        )
    low_level.version = server_version


def _release_line(raw_version: str) -> tuple[int, int] | None:
    release = raw_version.partition("+")[0].partition("-")[0].split(".")
    if len(release) < 2:
        return None
    try:
        return int(release[0]), int(release[1])
    except ValueError:
        return None
