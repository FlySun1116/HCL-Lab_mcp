"""Domain models for device runtime state and transport endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeviceState(StrEnum):
    """Runtime state of an HCL device."""

    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    PAUSED = "paused"


class TransportType(StrEnum):
    """Supported device transport channels."""

    CONSOLE_TELNET = "console_telnet"
    SSH = "ssh"
    NETCONF = "netconf"


class DiscoverySource(StrEnum):
    """Source of a runtime endpoint discovery."""

    CONFIG = "config"
    LOG = "log"
    PROBE = "probe"
    FORMULA = "formula"
    MANUAL = "manual"


class RuntimeEndpoint(BaseModel):
    """A discovered way to connect to a running device."""

    model_config = ConfigDict(frozen=True)

    transport: TransportType = Field(description="Transport protocol type")
    host: str = Field(default="127.0.0.1", description="IP address to connect to")
    port: int = Field(description="TCP port")
    source: DiscoverySource = Field(description="How this endpoint was discovered")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Discovery confidence 0.0–1.0")
    discovered_at: datetime | None = Field(default=None, description="When this endpoint was discovered")
    extra: dict[str, str] = Field(default_factory=dict, description="Additional metadata")

    def __repr__(self) -> str:
        return (
            f"RuntimeEndpoint({self.transport.value}://{self.host}:{self.port}"
            f", confidence={self.confidence:.0%}, source={self.source.value})"
        )


class DeviceRuntime(BaseModel):
    """Runtime status of a device discovered in an HCL project."""

    model_config = ConfigDict(frozen=True)

    device_id: int = Field(description="Device ID")
    device_name: str = Field(description="Device name")
    state: DeviceState = Field(default=DeviceState.UNKNOWN)
    endpoints: list[RuntimeEndpoint] = Field(default_factory=list)
    last_seen: datetime | None = Field(default=None)

    @property
    def is_running(self) -> bool:
        return self.state == DeviceState.RUNNING

    @property
    def console_available(self) -> bool:
        return any(e.transport == TransportType.CONSOLE_TELNET for e in self.endpoints)

    def best_endpoint(self, preferred: list[TransportType] | None = None) -> RuntimeEndpoint | None:
        """Return the best available endpoint by preference order."""
        if not self.endpoints:
            return None
        order = preferred or [TransportType.CONSOLE_TELNET, TransportType.SSH]
        for transport in order:
            for ep in self.endpoints:
                if ep.transport == transport:
                    return ep
        return self.endpoints[0]
