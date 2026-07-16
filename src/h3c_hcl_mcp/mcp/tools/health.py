"""Server health and diagnostics tool."""

from __future__ import annotations

import platform
import sys
import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.domain.errors import DomainError
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery
from h3c_hcl_mcp.version import VERSION


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register the server_health tool on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    project_repo: ProjectRepository = deps["project_repository"]
    runtime_discovery: RuntimeDiscovery = deps["runtime_discovery"]
    server_name = str(deps.get("server_name", "h3c-hcl-mcp"))

    @mcp.tool(
        name="server_health",
        description=(
            "Get server health status and version information. "
            "Use deep=True for a full health check including dependency status."
        ),
    )
    async def server_health(deep: bool = False) -> ToolResult:
        """Get server health status and version information.

        Args:
            deep: If True, run a full health check including dependency validation.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            data: dict[str, Any] = {
                "version": VERSION,
                "python_version": sys.version,
                "platform": platform.platform(),
                "server": server_name,
            }

            if deep:
                try:
                    projects, next_cursor = await project_repo.list_projects(limit=200)
                    data["hcl_projects_accessible"] = True
                    data["hcl_project_count"] = len(projects)
                    data["hcl_projects_truncated"] = next_cursor is not None
                except DomainError as e:
                    data["hcl_projects_accessible"] = False
                    data["hcl_projects_error"] = e.code.value
                    projects = []

                if projects:
                    try:
                        runtimes = await runtime_discovery.discover_project(projects[0].project_id)
                        data["runtime_discovery_status"] = "available"
                        data["runtime_device_count"] = len(runtimes)
                        data["runtime_running_count"] = sum(1 for runtime in runtimes if runtime.is_running)
                    except DomainError as e:
                        data["runtime_discovery_status"] = "degraded"
                        data["runtime_discovery_error"] = e.code.value
                else:
                    data["runtime_discovery_status"] = "not_tested_no_projects"

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=data,
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Unexpected error during health check")
