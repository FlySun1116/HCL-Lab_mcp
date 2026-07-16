"""Tools for tracking long-running asynchronous jobs."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from h3c_hcl_mcp.domain.errors import DomainError
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.job_store import JobStore


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register job management tools on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    job_store: JobStore = deps["job_store"]

    @mcp.tool(
        name="job_get",
        description=(
            "Get the status and result of an asynchronous job. "
            "Jobs are created for long-running operations like ping sweeps, "
            "bulk config collection, or batch commands."
        ),
    )
    async def job_get(job_id: Annotated[str, Field(min_length=1, max_length=128)]) -> ToolResult:
        """Get the status of an asynchronous job.

        Args:
            job_id: The job identifier to query.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            job_data = await job_store.get(job_id)

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data=job_data,
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get job status")

    @mcp.tool(
        name="job_cancel",
        description=(
            "Cancel a running or pending job. "
            "Jobs in completed or failed states cannot be cancelled. "
            "Returns whether the cancellation was successful."
        ),
    )
    async def job_cancel(job_id: Annotated[str, Field(min_length=1, max_length=128)]) -> ToolResult:
        """Cancel an asynchronous job.

        Args:
            job_id: The job identifier to cancel.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            cancelled = await job_store.cancel(job_id)

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "job_id": job_id,
                    "cancelled": cancelled,
                },
                changed=True,
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to cancel job")
