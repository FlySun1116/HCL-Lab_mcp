"""Domain models for command execution on network devices."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CommandType(str, Enum):
    """Classification of a CLI command."""

    DISPLAY = "display"
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"
    SAVE = "save"
    RESET = "reset"


class CommandTarget(BaseModel):
    """Fully-qualified device target for a command."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(description="HCL project ID")
    device_id: int = Field(description="Numeric device ID within the project")
    device_name: str | None = Field(default=None, description="Device name for cross-validation")

    def __repr__(self) -> str:
        return f"CommandTarget(project={self.project_id!r}, device={self.device_id})"


class CommandRequest(BaseModel):
    """A request to execute a command on a device."""

    model_config = ConfigDict(frozen=True)

    target: CommandTarget = Field(description="Target device")
    command: str = Field(description="CLI command text")
    command_type: CommandType = Field(default=CommandType.DISPLAY)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    max_output_chars: int = Field(default=32768, ge=1, le=1048576)
    redact: bool = Field(default=True, description="Redact sensitive output")


class CommandResult(BaseModel):
    """Result of a command execution on a device."""

    model_config = ConfigDict(frozen=True)

    target: CommandTarget = Field(description="Target device")
    command: str = Field(description="The command that was executed")
    raw_output: str = Field(default="", description="Raw device output")
    parsed_data: dict | None = Field(default=None, description="Structured parsed data if available")
    prompt_detected: str | None = Field(default=None, description="Device prompt after command")
    duration_ms: float = Field(default=0.0, description="Execution duration in milliseconds")
    truncated: bool = Field(default=False, description="Whether output was truncated")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings")
    content_trust: str = Field(
        default="untrusted_device_output",
        description="Trust annotation — device output is always untrusted",
    )
