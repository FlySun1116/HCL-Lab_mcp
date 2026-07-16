"""Protocol-level regression tests for validation and audit correlation."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

import anyio
import pytest
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.infrastructure.audit.store import SQLiteAuditStore
from h3c_hcl_mcp.infrastructure.settings import AuditSettings, HCLSettings
from h3c_hcl_mcp.mcp.audit_middleware import with_audit
from h3c_hcl_mcp.mcp.output_budget import with_output_budget
from h3c_hcl_mcp.mcp.server import create_server
from h3c_hcl_mcp.mcp.validation_middleware import wrap_call_tool_with_validation
from h3c_hcl_mcp.ports.audit_sink import AuditSink


class _MemoryAuditSink(AuditSink):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def query(
        self,
        request_id: str | None = None,
        tool: str | None = None,
        target_device: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        del target_device, since, until
        events = self.events
        if request_id is not None:
            events = [event for event in events if event.request_id == request_id]
        if tool is not None:
            events = [event for event in events if event.tool == tool]
        return events[:limit]


class _FailingAuditSink(AuditSink):
    async def append(self, event: AuditEvent) -> None:
        del event
        raise OSError("synthetic audit failure")

    async def query(
        self,
        request_id: str | None = None,
        tool: str | None = None,
        target_device: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        del request_id, tool, target_device, since, until, limit
        return []


async def _protocol_call(
    mcp: FastMCP,
    tool_name: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    """Call a FastMCP server through its registered JSON-RPC handler."""
    client_send, server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    server_send, client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    result: CallToolResult | None = None
    async with (
        server_receive,
        client_send,
        client_receive,
        server_send,
        anyio.create_task_group() as task_group,
    ):
        task_group.start_soon(
            mcp._mcp_server.run,
            server_receive,
            server_send,
            mcp._mcp_server.create_initialization_options(),
        )
        async with ClientSession(client_receive, client_send) as client:
            await client.initialize()
            result = await client.call_tool(tool_name, arguments)
        task_group.cancel_scope.cancel()

    assert result is not None
    return result


def _error_from_result(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is True
    assert result.content
    text = getattr(result.content[0], "text", None)
    assert isinstance(text, str)
    return json.loads(text[text.index("{") :])["error"]


async def test_successful_tool_fails_closed_when_audit_append_is_unavailable() -> None:
    server = FastMCP("audit-fail-closed-test")
    audit_sink = _FailingAuditSink()

    @server.tool(name="read_only_tool")
    @with_audit("read_only_tool", audit_sink)
    async def read_only_tool() -> ToolResult:
        return ToolResult.success(request_id="req-audit-failure", data={"value": "read"})

    wrap_call_tool_with_validation(server, audit_sink=audit_sink, max_output_bytes=1024)
    result = await _protocol_call(server, "read_only_tool", {})

    error = _error_from_result(result)
    assert error["code"] == ErrorCode.INTERNAL_ERROR.value
    assert error["reason"] == "AUDIT_UNAVAILABLE"
    assert error["request_id"] == "req-audit-failure"
    assert "synthetic audit failure" not in json.dumps(error)


async def test_validation_failure_reports_audit_unavailable_when_append_fails() -> None:
    server = FastMCP("validation-audit-fail-closed-test")
    audit_sink = _FailingAuditSink()

    @server.tool(name="validated_tool")
    async def validated_tool(count: int) -> dict[str, int]:
        return {"count": count}

    wrap_call_tool_with_validation(server, audit_sink=audit_sink, max_output_bytes=1024)
    result = await _protocol_call(server, "validated_tool", {"count": "invalid"})

    error = _error_from_result(result)
    assert error["code"] == ErrorCode.INTERNAL_ERROR.value
    assert error["reason"] == "AUDIT_UNAVAILABLE"
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert "synthetic audit failure" not in json.dumps(error)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "field", "constraint_key", "constraint_value"),
    [
        (
            "h3c_get_config",
            {"project_id": "x", "device_id": 1, "source": "snapshot"},
            "source",
            "allowed",
            ["running", "startup"],
        ),
        (
            "h3c_ping",
            {"project_id": "x", "device_id": 1, "destination": "192.0.2.1", "count": 0},
            "count",
            "minimum",
            1,
        ),
    ],
)
async def test_validation_is_structured_on_registered_protocol_handler(
    tmp_path: Any,
    tool_name: str,
    arguments: dict[str, Any],
    field: str,
    constraint_key: str,
    constraint_value: object,
) -> None:
    db_path = tmp_path / "audit.db"
    settings = HCLSettings(audit=AuditSettings(database=str(db_path)))
    server = create_server(settings=settings)

    result = await _protocol_call(server, tool_name, arguments)

    error = _error_from_result(result)
    assert error["code"] == "INVALID_ARGUMENT"
    assert error["message"] == "Invalid tool arguments"
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert error["fields"][0]["field"] == field
    assert error["fields"][0][constraint_key] == constraint_value
    serialized = json.dumps(error)
    assert "pydantic.dev" not in serialized
    assert "input_value" not in serialized

    store = SQLiteAuditStore(db_path=str(db_path))
    events = await store.query(request_id=error["request_id"], limit=10)
    assert len(events) == 1
    assert events[0].tool == tool_name
    assert events[0].error_code == "INVALID_ARGUMENT"
    assert events[0].policy_result == "not_evaluated"


async def test_validation_failure_uses_same_request_id_in_audit() -> None:
    server = FastMCP("validation-audit-test")
    audit_sink = _MemoryAuditSink()

    @server.tool(name="validated_tool")
    async def validated_tool(source: Literal["running", "startup"] = "running") -> dict[str, str]:
        return {"source": source}

    wrap_call_tool_with_validation(server, audit_sink=audit_sink)

    result = await _protocol_call(server, "validated_tool", {"source": "snapshot"})

    error = _error_from_result(result)
    assert len(audit_sink.events) == 1
    event = audit_sink.events[0]
    assert event.request_id == error["request_id"]
    assert event.tool == "validated_tool"
    assert event.error_code == "INVALID_ARGUMENT"
    assert event.policy_result == "not_evaluated"
    assert event.outcome == "error"


async def test_unknown_tool_is_structured_and_audited() -> None:
    server = FastMCP("unknown-tool-audit-test")
    audit_sink = _MemoryAuditSink()
    wrap_call_tool_with_validation(server, audit_sink=audit_sink)

    result = await _protocol_call(server, "does_not_exist", {"project_id": "lab"})

    error = _error_from_result(result)
    assert error["code"] == "INVALID_ARGUMENT"
    assert error["message"] == "Unknown tool"
    assert error["tool"] == "does_not_exist"
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert len(audit_sink.events) == 1
    event = audit_sink.events[0]
    assert event.request_id == error["request_id"]
    assert event.tool == "does_not_exist"
    assert event.target == {"project_id": "lab"}
    assert event.error_code == "INVALID_ARGUMENT"
    assert event.policy_result == "not_evaluated"
    assert event.outcome == "error"


async def test_final_protocol_result_obeys_utf8_budget_and_keeps_both_channels() -> None:
    server = FastMCP("output-budget-success-test")
    audit_sink = _MemoryAuditSink()

    @server.tool(name="bounded_tool")
    @with_audit("bounded_tool", audit_sink)
    @with_output_budget(1024)
    async def bounded_tool() -> ToolResult:
        return ToolResult.success(
            request_id="req-bounded",
            data={"status": "健康", "emoji": "✅"},
        )

    wrap_call_tool_with_validation(
        server,
        audit_sink=audit_sink,
        max_output_bytes=1024,
    )

    result = await _protocol_call(server, "bounded_tool", {})

    assert result.isError is not True
    assert result.structuredContent is not None
    assert result.content
    text = getattr(result.content[0], "text", None)
    assert isinstance(text, str)
    assert json.loads(text) == result.structuredContent
    assert "\n" not in text
    assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")) <= 1024
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].outcome == "success"


async def test_oversized_protocol_result_is_bounded_and_audited_as_error() -> None:
    server = FastMCP("output-budget-error-test")
    audit_sink = _MemoryAuditSink()

    @server.tool(name="oversized_tool")
    @with_audit("oversized_tool", audit_sink)
    @with_output_budget(1024)
    async def oversized_tool() -> ToolResult:
        return ToolResult.success(
            request_id="req-oversized",
            data={"raw_output": "设备输出😀" * 2000},
            content_trust="untrusted_device_output",
        )

    wrap_call_tool_with_validation(
        server,
        audit_sink=audit_sink,
        max_output_bytes=1024,
    )

    result = await _protocol_call(server, "oversized_tool", {})

    error = _error_from_result(result)
    assert error["code"] == ErrorCode.OUTPUT_TOO_LARGE.value
    assert error["request_id"] == "req-oversized"
    assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")) <= 1024
    assert len(audit_sink.events) == 1
    assert audit_sink.events[0].request_id == "req-oversized"
    assert audit_sink.events[0].error_code == ErrorCode.OUTPUT_TOO_LARGE.value
    assert audit_sink.events[0].outcome == "error"


async def test_oversized_unknown_name_and_target_are_bounded_in_error_and_audit() -> None:
    server = FastMCP("output-budget-invalid-test")
    audit_sink = _MemoryAuditSink()
    wrap_call_tool_with_validation(
        server,
        audit_sink=audit_sink,
        max_output_bytes=1024,
    )

    result = await _protocol_call(
        server,
        "x" * 5000,
        {"project_id": "项" * 5000, "device_id": "not-an-integer"},
    )

    error = _error_from_result(result)
    assert error["code"] == ErrorCode.INVALID_ARGUMENT.value
    assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")) <= 1024
    assert len(audit_sink.events) == 1
    event = audit_sink.events[0]
    assert len(event.tool) == 256
    assert event.target is not None
    assert len(str(event.target["project_id"])) == 256
    assert event.target["device_id"] == "not-an-integer"
    assert event.policy_result == "not_evaluated"
    assert event.outcome == "error"


async def test_global_tool_timeout_is_structured_and_audited() -> None:
    server = FastMCP("tool-timeout-audit-test")
    audit_sink = _MemoryAuditSink()

    @server.tool(name="slow_tool")
    async def slow_tool() -> dict[str, bool]:
        await anyio.sleep(0.2)
        return {"completed": True}

    tool = server._tool_manager.get_tool("slow_tool")
    assert tool is not None
    tool.fn = with_audit("slow_tool", audit_sink)(tool.fn)
    wrap_call_tool_with_validation(server, audit_sink=audit_sink, timeout_seconds=0.01)

    result = await _protocol_call(server, "slow_tool", {})

    error = _error_from_result(result)
    assert error["code"] == "TIMEOUT"
    assert error["message"] == "Tool execution timed out"
    assert error["timeout_seconds"] == 0.01
    assert len(audit_sink.events) == 1
    event = audit_sink.events[0]
    assert event.request_id == error["request_id"]
    assert event.tool == "slow_tool"
    assert event.error_code == "TIMEOUT"
    assert event.outcome == "error"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_code"),
    [
        ("hcl_get_topology", {"project_id": "missing"}, "PROJECT_NOT_FOUND"),
        ("h3c_diff_config", {"project_id": "x", "device_id": 1}, "NOT_IMPLEMENTED"),
        ("job_get", {"job_id": "missing"}, "INVALID_ARGUMENT"),
    ],
)
async def test_domain_error_uses_same_request_id_and_code_in_sqlite_audit(
    tmp_path: Any,
    tool_name: str,
    arguments: dict[str, Any],
    expected_code: str,
) -> None:
    db_path = tmp_path / "audit.db"
    settings = HCLSettings(audit=AuditSettings(database=str(db_path)))
    server = create_server(settings=settings)

    result = await _protocol_call(server, tool_name, arguments)

    error = _error_from_result(result)
    assert error["code"] == expected_code
    store = SQLiteAuditStore(db_path=str(db_path))
    events = await store.query(request_id=error["request_id"], limit=10)
    assert len(events) == 1
    assert events[0].tool == tool_name
    assert events[0].error_code == expected_code
    assert events[0].policy_result == "not_evaluated"
    assert events[0].outcome == "error"
