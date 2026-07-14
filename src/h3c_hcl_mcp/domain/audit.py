"""Domain model for audit events."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    """An immutable record of a tool invocation for audit trail."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(description="Unique event identifier")
    request_id: str = Field(description="Correlated MCP request ID")
    caller: str = Field(default="unknown", description="Caller identity")
    tool: str = Field(description="MCP tool name")
    target: dict | None = Field(default=None, description="Target descriptor")
    policy_result: str = Field(default="allowed", description="Policy decision")
    change_summary: str | None = Field(default=None, description="Summary of state changes")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = Field(default=0.0)
    error_code: str | None = Field(default=None, description="Error code if call failed")
