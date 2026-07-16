"""Integration tests for MCP tools — validates schemas, error mapping, and isError."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.settings import AuditSettings, HCLSettings
from h3c_hcl_mcp.mcp.error_mapping import map_domain_error
from h3c_hcl_mcp.mcp.server import create_server
from h3c_hcl_mcp.mcp.tools.h3c_read import _is_comware_candidate
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
        assert data["data"]["hcl_projects_accessible"] is True


class TestHCLProjects:
    def test_list_empty(self, server):
        _, data = _call(server, "hcl_list_projects")
        assert data["ok"] is True
        assert isinstance(data["data"]["projects"], list)

    def test_list_does_not_expose_local_project_paths(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        _, data = _call(server, "hcl_list_projects")

        assert data["data"]["projects"]
        assert all("path" not in project for project in data["data"]["projects"])

    def test_topology_not_found(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "hcl_get_topology", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_topology_does_not_expose_device_config_paths(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        _, data = _call(server, "hcl_get_topology", {"project_id": "hcl_sample_001"})

        assert data["data"]["devices"]
        assert all("config_path" not in device for device in data["data"]["devices"])

    def test_damaged_project_error_does_not_expose_local_path(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        with pytest.raises(ToolError) as exc:
            _call(server, "hcl_get_topology", {"project_id": "hcl_damaged_001"})

        error_data = _get_tool_error_json(exc.value)
        serialized = json.dumps(error_data, ensure_ascii=False)
        assert error_data["error"]["code"] == "PROJECT_DAMAGED"
        assert "path" not in error_data["error"]
        assert str(synthetic_projects_dir) not in serialized


class TestHCLRuntime:
    def test_nonexistent_project(self, server):
        """hcl_get_runtime should raise ToolError for nonexistent projects."""
        with pytest.raises(ToolError) as exc:
            _call(server, "hcl_get_runtime", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"


class TestH3CDevices:
    @pytest.mark.parametrize(
        ("model", "category", "version", "expected"),
        [
            ("S6850", "交换机", "CMW7.1.070", True),
            ("MSR36", "路由器", "", True),
            ("PC", "终端", "", False),
            ("vPC", "terminal", "", False),
        ],
    )
    def test_comware_candidate_filter(self, model, category, version, expected):
        assert _is_comware_candidate(model, category, version) is expected

    def test_list_not_found(self, server):
        with pytest.raises(ToolError) as exc:
            _call(server, "h3c_list_devices", {"project_id": "nonexistent"})
        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "PROJECT_NOT_FOUND"

    def test_direct_device_call_has_no_runtime_call_order_dependency(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        with pytest.raises(ToolError) as exc:
            _call(
                server,
                "h3c_run_display",
                {
                    "project_id": "hcl_sample_001",
                    "device_id": 1,
                    "command": "display version",
                },
            )

        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "DEVICE_NOT_RUNNING"

    def test_unredacted_config_is_policy_denied(self, server):
        with pytest.raises(ToolError) as exc:
            _call(
                server,
                "h3c_get_config",
                {"project_id": "x", "device_id": 1, "redact": False},
            )

        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "POLICY_DENIED"

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

    def test_explicitly_disabled_audit_does_not_create_database(self, tmp_path):
        database = tmp_path / "disabled-audit.db"
        settings = HCLSettings(audit=AuditSettings(enabled=False, database=str(database)))
        server = create_server(settings=settings)

        _call(server, "server_health", {"deep": False})
        _, data = _call(server, "audit_query")

        assert data["data"]["events"] == []
        assert not database.exists()

    @pytest.mark.parametrize(
        "arguments",
        [
            {"since": "not-a-time"},
            {"since": "2026-07-17T00:00:00Z", "until": "2026-07-16T00:00:00Z"},
        ],
    )
    def test_invalid_time_range_returns_invalid_argument(self, server, arguments):
        with pytest.raises(ToolError) as exc:
            _call(server, "audit_query", arguments)

        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "INVALID_ARGUMENT"


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

    def test_run_display_default_never_exceeds_schema_maximum(self):
        settings = HCLSettings(
            server={"max_tool_seconds": 600},
            devices={"command_timeout_seconds": 300},
        )
        server = create_server(settings=settings)

        tools = asyncio.run(server.list_tools())
        run_display = next(tool for tool in tools if tool.name == "h3c_run_display")
        timeout_schema = run_display.inputSchema["properties"]["timeout"]
        assert timeout_schema["default"] == 120
        assert timeout_schema["default"] <= timeout_schema["maximum"]


class TestErrorBoundary:
    def test_untrusted_console_output_is_not_exposed(self):
        error = DomainError(
            ErrorCode.PROMPT_TIMEOUT,
            "No CLI prompt detected",
            {
                "device_id": 1,
                "buffer_tail": "password cipher supersecret",
                "raw_output": "secret another-secret",
            },
        )

        with pytest.raises(ToolError) as exc:
            map_domain_error(error, "req-redaction")

        serialized = json.dumps(_get_tool_error_json(exc.value), ensure_ascii=False)
        assert "supersecret" not in serialized
        assert "another-secret" not in serialized
        assert "buffer_tail" not in serialized
        assert "raw_output" not in serialized
