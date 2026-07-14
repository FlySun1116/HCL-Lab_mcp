"""Domain models for configuration change plans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from h3c_hcl_mcp.domain.command import CommandTarget


class ChangePlan(BaseModel):
    """A validated, pending configuration change plan."""

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(description="Unique plan identifier")
    target: CommandTarget = Field(description="Target device")
    operations: list[str] = Field(description="Normalized CLI commands to apply")
    diff: str = Field(default="", description="Human-readable config diff")
    risk_level: str = Field(default="low", description="Risk assessment: low, medium, high")
    baseline_hash: str = Field(description="SHA-256 of running-config before change")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=300),
        description="Plan expiry time",
    )
    approval_token: str | None = Field(default=None, description="Consumed approval token")

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at
