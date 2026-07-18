"""Integration tests for MCP tools — validates schemas, error mapping, and isError."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.command import CommandRequest, CommandTarget, CommandType
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.policy.engine import PolicyEngineImpl
from h3c_hcl_mcp.infrastructure.settings import AuditSettings, HCLSettings
from h3c_hcl_mcp.mcp.error_mapping import map_domain_error
from h3c_hcl_mcp.mcp.server import create_server
from h3c_hcl_mcp.mcp.tools.h3c_read import (
    _classify_read_only_command,
    _is_comware_candidate,
    _public_parsed_data,
)
from h3c_hcl_mcp.version import VERSION


@pytest.fixture
def server(tmp_path) -> FastMCP:
    settings = HCLSettings(audit=AuditSettings(database=str(tmp_path / "audit.db")))
    return create_server(settings=settings)


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
        assert data["content_trust"] == "untrusted_device_output"

    def test_list_does_not_expose_local_project_paths(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        _, data = _call(server, "hcl_list_projects")

        assert data["data"]["projects"]
        assert all("path" not in project for project in data["data"]["projects"])

    def test_list_cursor_can_be_passed_back_for_next_page(self, synthetic_projects_dir):
        server = create_server(hcl_projects_dirs=[str(synthetic_projects_dir)])

        _, first = _call(server, "hcl_list_projects", {"limit": 1})
        next_cursor = first["data"]["next_cursor"]
        _, second = _call(
            server,
            "hcl_list_projects",
            {"limit": 1, "cursor": next_cursor},
        )

        assert first["data"]["projects"][0]["project_id"] != second["data"]["projects"][0]["project_id"]

    def test_list_schema_exposes_bounded_cursor(self, server):
        tools = asyncio.run(server.list_tools())
        tool = next(item for item in tools if item.name == "hcl_list_projects")

        cursor = tool.inputSchema["properties"]["cursor"]
        assert cursor["pattern"] == "^[0-9]*$"
        assert cursor["maxLength"] == 20

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
        assert data["content_trust"] == "untrusted_device_output"

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "command",
        ["ping -c 5 192.0.2.1", "tracert -m 30 192.0.2.1"],
    )
    async def test_diagnostic_tools_use_diagnostic_policy_category(self, command: str) -> None:
        command_type = _classify_read_only_command(command)
        request = CommandRequest(
            target=CommandTarget(project_id="test", device_id=1),
            command=command,
            command_type=command_type,
        )

        assert command_type == CommandType.DIAGNOSTIC
        assert await PolicyEngineImpl(HCLSettings().policy).validate_command(request)

    def test_parser_raw_output_is_not_duplicated_in_public_structured_data(self) -> None:
        parsed = _public_parsed_data(
            {
                "destination": "192.0.2.1",
                "raw": "raw device output",
                "_raw": "raw device output",
            }
        )
        assert parsed == {"destination": "192.0.2.1"}

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
        assert "start the target device" in error_data["error"]["next_action"]

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
        command_schema = run_display.inputSchema["properties"]["command"]
        project_schema = run_display.inputSchema["properties"]["project_id"]
        assert timeout_schema["default"] == 120
        assert timeout_schema["default"] <= timeout_schema["maximum"]
        assert command_schema["maxLength"] == 1024
        assert project_schema["maxLength"] == 256

    def test_run_display_rejects_oversized_command_before_device_lookup(self):
        server = create_server()

        with pytest.raises(ToolError) as exc:
            _call(
                server,
                "h3c_run_display",
                {
                    "project_id": "missing",
                    "device_id": 1,
                    "command": "display version " + "A" * 2_000,
                },
            )

        error_data = _get_tool_error_json(exc.value)
        assert error_data["error"]["code"] == "INVALID_ARGUMENT"
        assert error_data["error"]["fields"][0]["field"] == "command"
        assert error_data["error"]["fields"][0]["maxLength"] == 1024

    @pytest.mark.parametrize("tool_name", ["h3c_ping", "h3c_trace_route"])
    def test_diagnostic_destination_schema_rejects_cli_arguments(self, tool_name: str):
        server = create_server()
        tools = asyncio.run(server.list_tools())
        tool = next(candidate for candidate in tools if candidate.name == tool_name)
        destination = tool.inputSchema["properties"]["destination"]

        assert destination["minLength"] == 1
        assert destination["maxLength"] == 253
        assert destination["pattern"]


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
