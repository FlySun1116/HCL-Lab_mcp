"""Tools for discovering and inspecting HCL projects."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
            "Returns project summaries including name, device count, and last modified time. "
            "Pass next_cursor back as cursor to continue pagination."
        ),
    )
    async def hcl_list_projects(
        query: Annotated[str, Field(max_length=256, description="Optional name or ID filter")] = "",
        limit: Annotated[int, Field(ge=1, le=200, description="Maximum projects per page")] = 50,
        cursor: Annotated[
            str,
            Field(
                max_length=20,
                pattern=r"^[0-9]*$",
                description="Opaque cursor returned by the previous page",
            ),
        ] = "",
    ) -> ToolResult:
        """List HCL lab projects with optional query filtering.

        Args:
            query: Optional filter string to match against project names.
            limit: Maximum number of projects to return (1-200).
            cursor: Cursor returned in the previous page's next_cursor field.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            projects, next_cursor = await project_repo.list_projects(
                query=query if query else None,
                limit=limit,
                cursor=cursor if cursor else None,
            )

            # The repository needs absolute paths internally, but MCP clients
            # do not. Avoid exposing local usernames and directory layouts.
            public_projects = [
                {
                    "project_id": project.project_id,
                    "name": project.name,
                    "hcl_version": project.hcl_version,
                    "device_count": project.device_count,
                    "updated_at": project.updated_at,
                }
                for project in projects
            ]
            data: dict[str, Any] = {
                "projects": public_projects,
                "count": len(projects),
            }
            if next_cursor:
                data["next_cursor"] = next_cursor

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=data,
                duration_ms=round(duration_ms, 2),
                content_trust="untrusted_device_output",
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
    async def hcl_get_topology(
        project_id: Annotated[str, Field(min_length=1, max_length=256)],
    ) -> ToolResult:
        """Get the full topology for an HCL project.

        Args:
            project_id: The HCL project identifier (e.g. 'hcl_1e910d518140').
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            topology = await project_repo.get_topology(project_id)
            public_topology = topology.to_dict()
            devices = public_topology.get("devices")
            if isinstance(devices, list):
                for device in devices:
                    if isinstance(device, dict):
                        # Configuration file locations are an adapter concern.
                        # They may contain local usernames or untrusted absolute
                        # paths from copied project metadata.
                        device.pop("config_path", None)

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=public_topology,
                target={"project_id": project_id},
                warnings=topology.warnings,
                duration_ms=round(duration_ms, 2),
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get topology")
