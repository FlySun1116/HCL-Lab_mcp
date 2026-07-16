"""Tools for querying HCL device runtime state."""

from __future__ import annotations

import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.domain.errors import DomainError
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register HCL runtime tools on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    project_repo: ProjectRepository = deps["project_repository"]
    runtime_disc: RuntimeDiscovery = deps["runtime_discovery"]

    @mcp.tool(
        name="hcl_get_runtime",
        description=(
            "Get runtime state for all devices in an HCL project. "
            "Returns device states (running/stopped/starting/paused) and "
            "available console/SSH endpoints for each device."
        ),
    )
    async def hcl_get_runtime(project_id: str) -> ToolResult:
        """Get runtime state for all devices in an HCL project.

        Args:
            project_id: The HCL project identifier.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            # Validate project exists before checking runtime
            await project_repo.get_project(project_id)

            runtimes = await runtime_disc.discover_project(project_id)

            devices_data = []
            for rt in runtimes:
                endpoints_data = []
                for ep in rt.endpoints:
                    endpoints_data.append(
                        {
                            "transport": ep.transport.value,
                            "host": ep.host,
                            "port": ep.port,
                            "source": ep.source.value,
                            "confidence": ep.confidence,
                        }
                    )
                devices_data.append(
                    {
                        "device_id": rt.device_id,
                        "device_name": rt.device_name,
                        "state": rt.state.value,
                        "is_running": rt.is_running,
                        "console_available": rt.console_available,
                        "endpoints": endpoints_data,
                    }
                )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "project_id": project_id,
                    "devices": devices_data,
                    "running_count": sum(1 for rt in runtimes if rt.is_running),
                    "total_count": len(runtimes),
                },
                target={"project_id": project_id},
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get runtime state")
