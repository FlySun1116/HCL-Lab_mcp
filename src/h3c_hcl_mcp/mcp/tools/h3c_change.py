"""Placeholder tools for v0.2 write operations.

All tools in this module are currently disabled. They will be enabled
when the write path (plan/diff/approval/apply/verify) is implemented.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.domain.result import ToolResult


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register placeholder v0.2 change tools on the MCP server.

    These tools return a "not implemented in v0.1" message and will be
    fully implemented in v0.2.0 (plan/apply workflow).

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    _ = deps  # deps reserved for future v0.2 adapter injection

    @mcp.tool(
        name="h3c_plan_change",
        description=("Create a configuration change plan. NOT YET IMPLEMENTED — planned for v0.2.0."),
    )
    async def h3c_plan_change(
        project_id: str,
        device_id: int,
        changes: str = "",
    ) -> ToolResult:
        """Placeholder for configuration change planning (v0.2.0).

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            changes: Configuration changes in CLI format.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        duration_ms = (time.monotonic() - start) * 1000
        return ToolResult.success(
            request_id=request_id,
            data={
                "message": "Change planning is not yet available (planned for v0.2.0).",
                "feature_version": "0.2.0",
            },
            target={"project_id": project_id, "device_id": device_id},
            duration_ms=round(duration_ms, 2),
        )

    @mcp.tool(
        name="h3c_approve_change",
        description=("Approve a configuration change plan. NOT YET IMPLEMENTED — planned for v0.2.0."),
    )
    async def h3c_approve_change(plan_id: str) -> ToolResult:
        """Placeholder for change plan approval (v0.2.0).

        Args:
            plan_id: The change plan identifier to approve.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        duration_ms = (time.monotonic() - start) * 1000
        return ToolResult.success(
            request_id=request_id,
            data={
                "message": "Change approval is not yet available (planned for v0.2.0).",
                "plan_id": plan_id,
                "feature_version": "0.2.0",
            },
            duration_ms=round(duration_ms, 2),
        )

    @mcp.tool(
        name="h3c_apply_change",
        description=(
            "Apply an approved configuration change plan. NOT YET IMPLEMENTED — planned for v0.2.0."
        ),
    )
    async def h3c_apply_change(plan_id: str) -> ToolResult:
        """Placeholder for change plan application (v0.2.0).

        Args:
            plan_id: The change plan identifier to apply.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        duration_ms = (time.monotonic() - start) * 1000
        return ToolResult.success(
            request_id=request_id,
            data={
                "message": "Change application is not yet available (planned for v0.2.0).",
                "plan_id": plan_id,
                "feature_version": "0.2.0",
            },
            duration_ms=round(duration_ms, 2),
        )

    @mcp.tool(
        name="h3c_verify_change",
        description=(
            "Verify a configuration change was applied correctly. NOT YET IMPLEMENTED — planned for v0.2.0."
        ),
    )
    async def h3c_verify_change(plan_id: str) -> ToolResult:
        """Placeholder for change verification (v0.2.0).

        Args:
            plan_id: The change plan identifier to verify.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        duration_ms = (time.monotonic() - start) * 1000
        return ToolResult.success(
            request_id=request_id,
            data={
                "message": "Change verification is not yet available (planned for v0.2.0).",
                "plan_id": plan_id,
                "feature_version": "0.2.0",
            },
            duration_ms=round(duration_ms, 2),
        )
