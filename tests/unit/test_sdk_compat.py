"""Focused tests for the narrow MCP SDK private compatibility bridge."""

from __future__ import annotations

from importlib.metadata import version as distribution_version

import pytest
from mcp.server.fastmcp import FastMCP

import h3c_hcl_mcp.mcp.sdk_compat as sdk_compat


def test_locked_mcp_version_matches_verified_runtime() -> None:
    assert distribution_version("mcp") == sdk_compat.VERIFIED_MCP_VERSION


def test_version_bridge_rejects_unverified_mcp_minor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FastMCP("unsupported-sdk")
    monkeypatch.setattr(sdk_compat, "distribution_version", lambda _: "1.29.0")

    with pytest.raises(RuntimeError, match="Unsupported MCP Python SDK 1.29.0"):
        sdk_compat.set_fastmcp_server_version(server, "test-version")


def test_version_bridge_rejects_unexpected_fastmcp_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = object.__new__(FastMCP)
    monkeypatch.setattr(
        sdk_compat,
        "distribution_version",
        lambda _: sdk_compat.VERIFIED_MCP_VERSION,
    )

    with pytest.raises(RuntimeError, match="FastMCP structure is incompatible"):
        sdk_compat.set_fastmcp_server_version(server, "test-version")
