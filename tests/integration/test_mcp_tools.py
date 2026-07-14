"""Integration tests for all 19 MCP tools — validates schemas and error mapping."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.mcp.server import create_server


@pytest.fixture
def server() -> FastMCP:
    return create_server()


class TestServerHealth:
    def test_basic(self, server):
        async def run():
            _, data = await server.call_tool("server_health", {"deep": False})
            assert data["ok"] is True
            assert data["data"]["version"] == "0.0.1"

        asyncio.run(run())

    def test_deep(self, server):
        async def run():
            _, data = await server.call_tool("server_health", {"deep": True})
            assert data["ok"] is True
            assert "runtime_discovery_status" in data["data"]

        asyncio.run(run())


class TestHCLProjects:
    def test_list_empty(self, server):
        async def run():
            _, data = await server.call_tool("hcl_list_projects", {})
            assert data["ok"] is True
            assert isinstance(data["data"]["projects"], list)

        asyncio.run(run())

    def test_topology_not_found(self, server):
        async def run():
            _, data = await server.call_tool("hcl_get_topology", {"project_id": "nonexistent"})
            assert data["ok"] is False
            assert data["data"]["error"]["code"] == "PROJECT_NOT_FOUND"

        asyncio.run(run())


class TestHCLRuntime:
    def test_empty_runtime(self, server):
        async def run():
            _, data = await server.call_tool("hcl_get_runtime", {"project_id": "nonexistent"})
            assert data["ok"] is True
            assert data["data"]["devices"] == []

        asyncio.run(run())


class TestH3CDevices:
    def test_list_not_found(self, server):
        async def run():
            _, data = await server.call_tool("h3c_list_devices", {"project_id": "nonexistent"})
            assert data["ok"] is False
            assert data["data"]["error"]["code"] == "PROJECT_NOT_FOUND"

        asyncio.run(run())

    @pytest.mark.parametrize(
        "tool,params",
        [
            ("h3c_get_facts", {"project_id": "x", "device_id": 1}),
            ("h3c_get_config", {"project_id": "x", "device_id": 1}),
            ("h3c_get_interfaces", {"project_id": "x", "device_id": 1}),
            ("h3c_run_display", {"project_id": "x", "device_id": 1, "command": "display version"}),
            ("h3c_ping", {"project_id": "x", "device_id": 1, "destination": "1.1.1.1"}),
            ("h3c_trace_route", {"project_id": "x", "device_id": 1, "destination": "1.1.1.1"}),
            ("h3c_diff_config", {"project_id": "x", "device_id": 1}),
        ],
    )
    def test_device_tools_no_crash(self, server, tool, params):
        async def run():
            _, data = await server.call_tool(tool, params)
            assert isinstance(data, dict)
            assert "ok" in data

        asyncio.run(run())


class TestJobs:
    def test_get_not_found(self, server):
        async def run():
            _, data = await server.call_tool("job_get", {"job_id": "nonexistent"})
            assert data["ok"] is False
            assert "error" in data["data"]

        asyncio.run(run())

    def test_cancel_no_crash(self, server):
        async def run():
            _, data = await server.call_tool("job_cancel", {"job_id": "nonexistent"})
            assert isinstance(data, dict)
            assert "ok" in data

        asyncio.run(run())


class TestAudit:
    def test_query_empty(self, server):
        async def run():
            _, data = await server.call_tool("audit_query", {})
            assert data["ok"] is True
            assert isinstance(data["data"]["events"], list)

        asyncio.run(run())


class TestV02Placeholders:
    @pytest.mark.parametrize(
        "tool,params",
        [
            ("h3c_plan_change", {"project_id": "x", "device_id": 1, "changes": "test"}),
            ("h3c_approve_change", {"plan_id": "x"}),
            ("h3c_apply_change", {"plan_id": "x"}),
            ("h3c_verify_change", {"plan_id": "x"}),
        ],
    )
    def test_placeholder_no_crash(self, server, tool, params):
        async def run():
            _, data = await server.call_tool(tool, params)
            assert isinstance(data, dict)
            assert "ok" in data

        asyncio.run(run())
