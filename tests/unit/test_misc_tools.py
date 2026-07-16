"""Positive and failure-path tests for runtime, health, and job tools."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import LabProject
from h3c_hcl_mcp.mcp.tools import hcl_runtime, health, jobs


def _call(server: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _, structured = asyncio.run(server.call_tool(name, arguments))
    return structured


class _Projects:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.projects = [LabProject(project_id="lab", name="Lab", path="hidden")]

    async def get_project(self, project_id: str) -> LabProject:
        if self.failure is not None:
            raise self.failure
        if project_id != "lab":
            raise DomainError(ErrorCode.PROJECT_NOT_FOUND, "missing")
        return self.projects[0]

    async def list_projects(self, **kwargs: Any) -> tuple[list[LabProject], str | None]:
        del kwargs
        if self.failure is not None:
            raise self.failure
        return self.projects, None


class _Runtime:
    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.runtimes = [
            DeviceRuntime(
                device_id=1,
                device_name="S6850_1",
                state=DeviceState.RUNNING,
                endpoints=[
                    RuntimeEndpoint(
                        transport=TransportType.CONSOLE_TELNET,
                        host="127.0.0.1",
                        port=30001,
                        source=DiscoverySource.LOG,
                        confidence=0.9,
                    )
                ],
            ),
            DeviceRuntime(
                device_id=2,
                device_name="S6850_2",
                state=DeviceState.STOPPED,
            ),
        ]

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        assert project_id == "lab"
        if self.failure is not None:
            raise self.failure
        return self.runtimes


def test_runtime_tool_returns_devices_endpoints_and_counts() -> None:
    server = FastMCP("runtime-positive")
    hcl_runtime.register(
        server,
        project_repository=_Projects(),
        runtime_discovery=_Runtime(),
    )

    result = _call(server, "hcl_get_runtime", {"project_id": "lab"})

    assert result["ok"] is True
    assert result["data"]["total_count"] == 2
    assert result["data"]["running_count"] == 1
    running = result["data"]["devices"][0]
    assert running["console_available"] is True
    assert running["endpoints"][0] == {
        "transport": "console_telnet",
        "host": "127.0.0.1",
        "port": 30001,
        "source": "log",
        "confidence": 0.9,
    }


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (DomainError(ErrorCode.PROJECT_NOT_FOUND, "missing"), ErrorCode.PROJECT_NOT_FOUND),
        (RuntimeError("private runtime detail"), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_runtime_tool_maps_domain_and_internal_errors(
    failure: Exception,
    expected_code: ErrorCode,
) -> None:
    server = FastMCP("runtime-errors")
    projects = _Projects()
    projects.failure = failure
    hcl_runtime.register(
        server,
        project_repository=projects,
        runtime_discovery=_Runtime(),
    )

    with pytest.raises(ToolError) as exc_info:
        _call(server, "hcl_get_runtime", {"project_id": "lab"})

    message = str(exc_info.value)
    assert expected_code.value in message
    assert "private runtime detail" not in message


def test_deep_health_checks_projects_and_runtime() -> None:
    server = FastMCP("health-positive")
    health.register(
        server,
        project_repository=_Projects(),
        runtime_discovery=_Runtime(),
        server_name="test-server",
    )

    result = _call(server, "server_health", {"deep": True})

    assert result["data"]["server"] == "test-server"
    assert result["data"]["hcl_projects_accessible"] is True
    assert result["data"]["hcl_project_count"] == 1
    assert result["data"]["runtime_discovery_status"] == "available"
    assert result["data"]["runtime_device_count"] == 2
    assert result["data"]["runtime_running_count"] == 1


def test_deep_health_reports_domain_degradation_without_failing() -> None:
    projects = _Projects()
    runtime = _Runtime()
    runtime.failure = DomainError(ErrorCode.CONSOLE_UNAVAILABLE, "unavailable")
    server = FastMCP("health-degraded-runtime")
    health.register(server, project_repository=projects, runtime_discovery=runtime)

    result = _call(server, "server_health", {"deep": True})

    assert result["ok"] is True
    assert result["data"]["runtime_discovery_status"] == "degraded"
    assert result["data"]["runtime_discovery_error"] == ErrorCode.CONSOLE_UNAVAILABLE.value

    projects.failure = DomainError(ErrorCode.PROJECT_DAMAGED, "damaged")
    result = _call(server, "server_health", {"deep": True})
    assert result["data"]["hcl_projects_accessible"] is False
    assert result["data"]["hcl_projects_error"] == ErrorCode.PROJECT_DAMAGED.value
    assert result["data"]["runtime_discovery_status"] == "not_tested_no_projects"


def test_deep_health_maps_unexpected_dependency_error() -> None:
    projects = _Projects()
    projects.failure = RuntimeError("private health detail")
    server = FastMCP("health-error")
    health.register(server, project_repository=projects, runtime_discovery=_Runtime())

    with pytest.raises(ToolError) as exc_info:
        _call(server, "server_health", {"deep": True})

    message = str(exc_info.value)
    assert ErrorCode.INTERNAL_ERROR.value in message
    assert "private health detail" not in message


class _Jobs:
    def __init__(self) -> None:
        self.failure: Exception | None = None

    async def get(self, job_id: str) -> dict[str, Any]:
        if self.failure is not None:
            raise self.failure
        return {"job_id": job_id, "status": "completed", "result": {"value": 1}}

    async def cancel(self, job_id: str) -> bool:
        if self.failure is not None:
            raise self.failure
        return job_id == "running"


def test_job_tools_return_status_and_cancellation() -> None:
    server = FastMCP("jobs-positive")
    store = _Jobs()
    jobs.register(server, job_store=store)

    status = _call(server, "job_get", {"job_id": "done"})
    cancelled = _call(server, "job_cancel", {"job_id": "running"})

    assert status["data"]["status"] == "completed"
    assert status["data"]["result"] == {"value": 1}
    assert cancelled["data"] == {"job_id": "running", "cancelled": True}
    assert cancelled["changed"] is True


@pytest.mark.parametrize(
    ("tool_name", "failure", "expected_code"),
    [
        ("job_get", DomainError(ErrorCode.INVALID_ARGUMENT, "missing"), ErrorCode.INVALID_ARGUMENT),
        ("job_cancel", DomainError(ErrorCode.INVALID_ARGUMENT, "missing"), ErrorCode.INVALID_ARGUMENT),
        ("job_get", RuntimeError("private job detail"), ErrorCode.INTERNAL_ERROR),
        ("job_cancel", RuntimeError("private job detail"), ErrorCode.INTERNAL_ERROR),
    ],
)
def test_job_tools_map_domain_and_internal_errors(
    tool_name: str,
    failure: Exception,
    expected_code: ErrorCode,
) -> None:
    server = FastMCP("jobs-errors")
    store = _Jobs()
    store.failure = failure
    jobs.register(server, job_store=store)

    with pytest.raises(ToolError) as exc_info:
        _call(server, tool_name, {"job_id": "missing"})

    message = str(exc_info.value)
    assert expected_code.value in message
    assert "private job detail" not in message
