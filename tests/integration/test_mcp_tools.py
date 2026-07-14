"""Integration tests for MCP tools — validates schemas, error mapping, and isError."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.mcp.server import create_server
from h3c_hcl_mcp.version import VERSION


@pytest.fixture
def server() -> FastMCP:
    return create_server()


def _call(server, tool_name, args=None):
    """Call a tool and return (contents, data) or raise ToolError."""
    return asyncio.run(server.call_tool(tool_name, args or {}))


def _get_tool_error_json(exc: ToolError) -> dict:
    """Extract structured error data from a ToolError message."""
    msg = str(exc)
    # Format: "Error executing tool NAME: {json}"
    json_start = msg.index("{")
    return json.loads(msg[json_start:])


class TestServerHealth:
    def test_basic(self, server):
        _, data = _call(server, "server_health", {"deep": False})
        assert data["ok"] is True
        assert data["data"]["version"] == VERSION

    def test_deep(self, server):
        _, data = _call(server, "server_health", {"deep": True})
        assert data["ok"] is True
        assert "runtime_discovery_status" in data["data"]


class TestHCLProjects:
    def test_list_empty(self, server):
        _, data = _call(server, "hcl_list_projects")
        assert data["ok"] is True
        assert isinstance(data["data"]["projects"], list)

    def test_topology_not_found(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "hcl_get_topology", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"


class TestHCLRuntime:
    def test_nonexistent_project(self, server):
        """hcl_get_runtime should raise ToolError for nonexistent projects."""
        with pytest.raises(ToolError) as exc:
            _call(server, "hcl_get_runtime", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"


class TestH3CDevices:
    def test_list_not_found(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "h3c_list_devices", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"

    @pytest.mark.parametrize(
        "tool,params",
        [
            ("h3c_get_facts", {"project_id": "x", "device_id": 1}),
            ("h3c_get_config", {"project_id": "x", "device_id": 1}),
            ("h3c_get_interfaces", {"project_id": "x", "device_id": 1}),
            ("h3c_run_display", {"project_id": "x", "device_id": 1, "command": "display version"}),
            ("h3c_ping", {"project_id": "x", "device_id": 1, "destination": "1.1.1.1"}),
            ("h3c_trace_route", {"project_id": "x", "device_id": 1, "destination": "1.1.1.1"}),
        ],
    )
    def test_device_tools_raise_iserror(self, server, tool, params):
        """All device tools should raise ToolError (isError=true) for missing devices."""
        with pytest.raises(ToolError):
            _call(server, tool, params)

    def test_diff_config_not_implemented(self, server):
        """h3c_diff_config should raise ToolError with NOT_IMPLEMENTED."""
        with pytest.raises(ToolError) as exc:
            _call(server, "h3c_diff_config", {"project_id": "x", "device_id": 1})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "NOT_IMPLEMENTED"


class TestJobs:
    def test_get_not_found(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "job_get", {"job_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert "error" in error_data

    def test_cancel_no_crash(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "job_cancel", {"job_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert "error" in error_data


class TestAudit:
    def test_query_empty(self, server):
        _, data = _call(server, "audit_query")
        assert data["ok"] is True
        assert isinstance(data["data"]["events"], list)


class TestV02ToolsRemoved:
    """v0.2 placeholder tools must NOT be registered in v0.1."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "h3c_plan_change",
            "h3c_approve_change",
            "h3c_apply_change",
            "h3c_verify_change",
        ],
    )
    def test_v02_tools_not_registered(self, server, tool_name):
        """Verify v0.2 placeholder tools are not exposed."""
        with pytest.raises(ToolError):
            _call(server, tool_name)


class TestToolCount:
    def test_v01_tool_count(self, server):
        """v0.1 should have 15 tools (not including v0.2 placeholders)."""
        result = asyncio.run(server.list_tools())
        tool_names = [t.name for t in result]
        # 15 tools: health, 2 hcl, 1 hcl_runtime, 1 h3c_list, 7 h3c_read,
        #           2 jobs, 1 audit. 4 v0.2 placeholders removed.
        assert len(tool_names) == 15, f"Expected 15 tools, got {len(tool_names)}: {tool_names}"
        assert "h3c_plan_change" not in tool_names
        assert "h3c_diff_config" in tool_names  # kept but returns NOT_IMPLEMENTED error
