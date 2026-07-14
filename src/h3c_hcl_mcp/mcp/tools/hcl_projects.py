"""Tools for discovering and inspecting HCL projects."""

from __future__ import annotations

import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.domain.errors import DomainError
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.project_repository import ProjectRepository


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register HCL project tools on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    project_repo: ProjectRepository = deps["project_repository"]

    @mcp.tool(
        name="hcl_list_projects",
        description=(
            "List HCL lab projects discovered on this machine. "
            "Returns project summaries including name, device count, and last modified time."
        ),
    )
    async def hcl_list_projects(
        query: str = "",
        limit: int = 50,
    ) -> ToolResult:
        """List HCL lab projects with optional query filtering.

        Args:
            query: Optional filter string to match against project names.
            limit: Maximum number of projects to return (1-200).
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            projects, next_cursor = await project_repo.list_projects(
                query=query if query else None,
                limit=max(1, min(limit, 200)),
            )

            data: dict[str, Any] = {
                "projects": [p.model_dump() for p in projects],
                "count": len(projects),
            }
            if next_cursor:
                data["next_cursor"] = next_cursor

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=data,
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to list HCL projects")

    @mcp.tool(
        name="hcl_get_topology",
        description=(
            "Get the full topology of an HCL project: devices, links, and warnings. "
            "Returns structured device references and inter-device connections."
        ),
    )
    async def hcl_get_topology(project_id: str) -> ToolResult:
        """Get the full topology for an HCL project.

        Args:
            project_id: The HCL project identifier (e.g. 'hcl_1e910d518140').
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            topology = await project_repo.get_topology(project_id)

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=topology.to_dict(),
                target={"project_id": project_id},
                warnings=topology.warnings,
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get topology")
