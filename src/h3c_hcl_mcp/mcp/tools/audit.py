"""Tool for querying the audit trail."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.audit_sink import AuditSink


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register audit tools on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    audit_sink: AuditSink = deps["audit_sink"]

    @mcp.tool(
        name="audit_query",
        description=(
            "Query the audit trail for past tool invocations. "
            "Filter by request ID, tool name, target device, or time range. "
            "Returns events in reverse chronological order."
        ),
    )
    async def audit_query(
        request_id: str = "",
        tool: str = "",
        target_device: Annotated[int, Field(ge=0, description="Target device ID")] = 0,
        since: str = "",
        until: str = "",
        limit: Annotated[int, Field(ge=1, le=500, description="Maximum events")] = 100,
    ) -> ToolResult:
        """Query audit events with optional filters.

        Args:
            request_id: Filter by specific MCP request ID.
            tool: Filter by tool name (e.g. 'h3c_get_facts').
            target_device: Filter by target device ID.
            since: ISO-8601 start time (e.g. '2026-01-01T00:00:00Z').
            until: ISO-8601 end time.
            limit: Maximum number of events to return (1-500).
        """
        req_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            # Parse optional datetime filters
            since_dt: datetime | None = None
            until_dt: datetime | None = None

            try:
                if since:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    if since_dt.tzinfo is None:
                        since_dt = since_dt.replace(tzinfo=UTC)
                if until:
                    until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                    if until_dt.tzinfo is None:
                        until_dt = until_dt.replace(tzinfo=UTC)
            except ValueError as error:
                raise DomainError(
                    ErrorCode.INVALID_ARGUMENT,
                    "since and until must be ISO-8601 timestamps",
                ) from error
            if since_dt is not None and until_dt is not None and since_dt > until_dt:
                raise DomainError(
                    ErrorCode.INVALID_ARGUMENT,
                    "since must not be later than until",
                )

            events = await audit_sink.query(
                request_id=request_id if request_id else None,
                tool=tool if tool else None,
                target_device=target_device if target_device > 0 else None,
                since=since_dt,
                until=until_dt,
                limit=limit,
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=req_id,
                data={
                    "events": [e.model_dump() for e in events],
                    "count": len(events),
                    "limit": limit,
                },
                duration_ms=round(duration_ms, 2),
            )

        except DomainError as e:
            return map_domain_error(e, req_id)
        except Exception:
            return internal_error(req_id, "Failed to query audit trail")
