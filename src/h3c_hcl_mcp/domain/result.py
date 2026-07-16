"""Unified tool result model — returned by all MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolResult(BaseModel):
    """Unified return structure for all MCP tools.

    All tools return this structure so MCP clients can rely on
    a consistent envelope regardless of tool-specific data.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool = Field(description="Whether the tool call succeeded")
    request_id: str = Field(description="Unique request identifier for tracing/audit")
    target: dict[str, Any] | None = Field(
        default=None,
        description="Target descriptor (project_id, device, etc.)",
    )
    changed: bool = Field(default=False, description="Whether this call modified device state")
    data: dict[str, Any] | None = Field(default=None, description="Tool-specific structured result")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings")
    duration_ms: float = Field(default=0.0, description="Server-side execution duration")
    truncated: bool = Field(default=False, description="Whether any public output was truncated")
    content_trust: Literal["trusted_server_data", "untrusted_device_output"] = Field(
        default="trusted_server_data",
        description="Whether result content originates from untrusted device output",
    )

    @classmethod
    def success(
        cls,
        request_id: str,
        data: dict[str, Any] | None = None,
        *,
        target: dict[str, Any] | None = None,
        changed: bool = False,
        warnings: list[str] | None = None,
        duration_ms: float = 0.0,
        truncated: bool = False,
        content_trust: Literal["trusted_server_data", "untrusted_device_output"] = "trusted_server_data",
    ) -> ToolResult:
        return cls(
            ok=True,
            request_id=request_id,
            target=target,
            changed=changed,
            data=data or {},
            warnings=warnings or [],
            duration_ms=duration_ms,
            truncated=truncated,
            content_trust=content_trust,
        )

    @classmethod
    def failure(
        cls,
        request_id: str,
        code: str,
        message: str,
        *,
        target: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
    ) -> ToolResult:
        return cls(
            ok=False,
            request_id=request_id,
            target=target,
            changed=False,
            data={"error": {"code": code, "message": message, **(details or {})}},
            duration_ms=duration_ms,
        )
