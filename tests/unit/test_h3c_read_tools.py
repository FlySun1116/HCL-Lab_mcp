"""Positive dependency-injected tests for the v0.1 H3C read tools."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.command import CommandRequest, CommandResult, CommandType
from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import DeviceRef, Topology
from h3c_hcl_mcp.infrastructure.settings import DeviceSettings, ServerSettings
from h3c_hcl_mcp.mcp.tools import h3c_read


class _ProjectRepository:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.topology = Topology(
            project_id="lab",
            devices=[
                DeviceRef(
                    project_id="lab",
                    device_id=1,
                    name="S6850_1",
                    model="S6850",
                    category="switch",
                    comware_version="Comware 7",
                ),
                DeviceRef(
                    project_id="lab",
                    device_id=2,
                    name="PC_1",
                    model="PC",
                    category="terminal",
                ),
            ],
        )

    async def get_topology(self, project_id: str) -> Topology:
        if self.failure is not None:
            raise self.failure
        if project_id != "lab":
            raise DomainError(ErrorCode.PROJECT_NOT_FOUND, "missing")
        return self.topology


class _RuntimeDiscovery:
    def __init__(self, *, running: bool = True, endpoint: bool = True) -> None:
        self.runtime = DeviceRuntime(
            device_id=1,
            device_name="S6850_1",
            state=DeviceState.RUNNING if running else DeviceState.STOPPED,
            endpoints=(
                [
                    RuntimeEndpoint(
                        transport=TransportType.CONSOLE_TELNET,
                        host="127.0.0.1",
                        port=30001,
                        source=DiscoverySource.LOG,
                        confidence=1.0,
                    )
                ]
                if endpoint
                else []
            ),
        )

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        assert project_id == "lab"
        return [self.runtime]

    async def discover_device(self, project_id: str, device_id: int) -> DeviceRuntime:
        assert project_id == "lab"
        assert device_id == 1
        return self.runtime


class _Transport:
    def __init__(self) -> None:
        self.connected: list[RuntimeEndpoint] = []
        self.requests: list[CommandRequest] = []
        self.close_count = 0
        self.failure: Exception | None = None

    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        self.connected.append(endpoint)

    async def execute(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return CommandResult(
            target=request.target,
            command=request.command,
            raw_output=(
                f"{request.command}\nsnmp-agent community read cipher NEVER_EXPOSE_THIS\ncommand completed"
            ),
            prompt_detected="<S6850_1>",
            warnings=["synthetic warning"],
        )

    async def close(self) -> None:
        self.close_count += 1


class _Parser:
    def __init__(self) -> None:
        self.raise_domain_error = False

    def parse(self, raw_output: str, model: str, version: str, command: str) -> dict[str, Any]:
        del model, version
        if self.raise_domain_error:
            raise DomainError(ErrorCode.COMMAND_PARSE_ERROR, "synthetic parse failure")
        if command == "display version":
            return {"system_name": "S6850_1", "software_version": "7.1", "raw": raw_output}
        if command == "display interface brief":
            return {
                "interfaces": [{"name": "GE1/0/1", "link": "UP"}],
                "_raw": raw_output,
            }
        if command == "ping":
            return {"sent": 2, "received": 2, "loss_percent": 0.0, "raw": raw_output}
        if command == "tracert":
            return {"hops": [{"index": 1, "address": "192.0.2.1"}], "_raw": raw_output}
        return {"parsed_command": command, "raw": raw_output}


class _Policy:
    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []

    async def validate_command(self, request: CommandRequest) -> bool:
        self.requests.append(request)
        return True


def _server(
    *,
    runtime: _RuntimeDiscovery | None = None,
) -> tuple[FastMCP, _ProjectRepository, _Transport, _Parser, _Policy]:
    server = FastMCP("h3c-read-positive-test")
    repository = _ProjectRepository()
    transport = _Transport()
    parser = _Parser()
    policy = _Policy()
    h3c_read.register(
        server,
        project_repository=repository,
        runtime_discovery=runtime or _RuntimeDiscovery(),
        device_transport=transport,
        command_parser=parser,
        policy_engine=policy,
        server_settings=ServerSettings(),
        device_settings=DeviceSettings(),
    )
    return server, repository, transport, parser, policy


def _call(server: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _, structured = asyncio.run(server.call_tool(name, arguments))
    return structured


def _error(exc: ToolError) -> str:
    return str(exc)


def test_list_devices_filters_terminal_nodes_and_marks_operability() -> None:
    server, _, _, _, _ = _server()

    result = _call(server, "h3c_list_devices", {"project_id": "lab"})

    assert result["ok"] is True
    assert result["content_trust"] == "untrusted_device_output"
    assert result["data"]["total_count"] == 1
    assert result["data"]["operable_count"] == 1
    assert result["data"]["devices"][0]["name"] == "S6850_1"
    assert result["data"]["devices"][0]["operable"] is True


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_command", "expected_type"),
    [
        ("h3c_get_facts", {"project_id": "lab", "device_id": 1}, "display version", CommandType.DISPLAY),
        (
            "h3c_run_display",
            {"project_id": "lab", "device_id": 1, "command": "display ip interface brief"},
            "display ip interface brief",
            CommandType.DISPLAY,
        ),
        (
            "h3c_get_config",
            {"project_id": "lab", "device_id": 1, "source": "startup"},
            "display saved-configuration",
            CommandType.DISPLAY,
        ),
        (
            "h3c_get_interfaces",
            {"project_id": "lab", "device_id": 1},
            "display interface brief",
            CommandType.DISPLAY,
        ),
        (
            "h3c_ping",
            {"project_id": "lab", "device_id": 1, "destination": "192.0.2.1", "count": 2},
            "ping -c 2 192.0.2.1",
            CommandType.DIAGNOSTIC,
        ),
        (
            "h3c_trace_route",
            {"project_id": "lab", "device_id": 1, "destination": "192.0.2.1", "max_hops": 5},
            "tracert -m 5 192.0.2.1",
            CommandType.DIAGNOSTIC,
        ),
    ],
)
def test_all_read_tools_execute_through_policy_transport_and_redaction(
    tool_name: str,
    arguments: dict[str, Any],
    expected_command: str,
    expected_type: CommandType,
) -> None:
    server, _, transport, _, policy = _server()

    result = _call(server, tool_name, arguments)

    assert result["ok"] is True
    assert result["content_trust"] == "untrusted_device_output"
    assert transport.requests[-1].command == expected_command
    assert transport.requests[-1].command_type == expected_type
    assert policy.requests[-1] == transport.requests[-1]
    assert transport.close_count == 1
    assert "NEVER_EXPOSE_THIS" not in str(result["data"])


def test_running_config_uses_current_configuration_command() -> None:
    server, _, transport, _, _ = _server()

    result = _call(
        server,
        "h3c_get_config",
        {"project_id": "lab", "device_id": 1, "source": "running"},
    )

    assert result["data"]["source"] == "running"
    assert transport.requests[-1].command == "display current-configuration"


def test_run_display_tolerates_parser_domain_error() -> None:
    server, _, _, parser, _ = _server()
    parser.raise_domain_error = True

    result = _call(
        server,
        "h3c_run_display",
        {"project_id": "lab", "device_id": 1, "command": "display version"},
    )

    assert result["ok"] is True
    assert result["data"]["parsed"] is None


@pytest.mark.parametrize(
    ("runtime", "expected_code"),
    [
        (_RuntimeDiscovery(running=False), ErrorCode.DEVICE_NOT_RUNNING),
        (_RuntimeDiscovery(endpoint=False), ErrorCode.CONSOLE_UNAVAILABLE),
    ],
)
def test_runtime_preconditions_return_stable_errors(
    runtime: _RuntimeDiscovery,
    expected_code: ErrorCode,
) -> None:
    server, _, transport, _, _ = _server(runtime=runtime)

    with pytest.raises(ToolError) as exc_info:
        _call(server, "h3c_get_facts", {"project_id": "lab", "device_id": 1})

    assert expected_code.value in _error(exc_info.value)
    assert transport.close_count == 0


def test_transport_failure_still_closes_connection() -> None:
    server, _, transport, _, _ = _server()
    transport.failure = DomainError(ErrorCode.CONNECTION_CLOSED, "synthetic disconnect")

    with pytest.raises(ToolError) as exc_info:
        _call(server, "h3c_get_facts", {"project_id": "lab", "device_id": 1})

    assert ErrorCode.CONNECTION_CLOSED.value in _error(exc_info.value)
    assert transport.close_count == 1


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("h3c_get_facts", {"project_id": "lab", "device_id": 1}),
        (
            "h3c_run_display",
            {"project_id": "lab", "device_id": 1, "command": "display version"},
        ),
        ("h3c_get_config", {"project_id": "lab", "device_id": 1}),
        ("h3c_get_interfaces", {"project_id": "lab", "device_id": 1}),
        (
            "h3c_ping",
            {"project_id": "lab", "device_id": 1, "destination": "192.0.2.1"},
        ),
        (
            "h3c_trace_route",
            {"project_id": "lab", "device_id": 1, "destination": "192.0.2.1"},
        ),
    ],
)
def test_unexpected_transport_errors_use_stable_internal_error(
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    server, _, transport, _, _ = _server()
    transport.failure = RuntimeError("do not expose this adapter failure")

    with pytest.raises(ToolError) as exc_info:
        _call(server, tool_name, arguments)

    message = _error(exc_info.value)
    assert ErrorCode.INTERNAL_ERROR.value in message
    assert "do not expose this adapter failure" not in message
    assert transport.close_count == 1


def test_list_devices_maps_domain_and_unexpected_repository_errors() -> None:
    server, repository, _, _, _ = _server()

    with pytest.raises(ToolError) as domain_exc:
        _call(server, "h3c_list_devices", {"project_id": "missing"})
    assert ErrorCode.PROJECT_NOT_FOUND.value in _error(domain_exc.value)

    repository.failure = RuntimeError("private repository detail")
    with pytest.raises(ToolError) as internal_exc:
        _call(server, "h3c_list_devices", {"project_id": "lab"})
    message = _error(internal_exc.value)
    assert ErrorCode.INTERNAL_ERROR.value in message
    assert "private repository detail" not in message


def test_empty_command_classifies_as_display() -> None:
    assert h3c_read._classify_read_only_command("") is CommandType.DISPLAY
