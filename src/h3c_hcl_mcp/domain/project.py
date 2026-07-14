"""Domain models for HCL projects, devices, and topology."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LabProject(BaseModel):
    """An HCL lab project discovered on the local machine."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(description="Unique project identifier (e.g. 'hcl_1e910d518140')")
    name: str = Field(description="Human-readable project name")
    path: str = Field(description="Absolute path to the project directory")
    hcl_version: str | None = Field(default=None, description="HCL version that created this project")
    device_count: int = Field(default=0, description="Number of devices in the project")
    updated_at: datetime | None = Field(default=None, description="Last modification timestamp")

    def __repr__(self) -> str:
        return f"LabProject(id={self.project_id!r}, name={self.name!r})"


class DeviceRef(BaseModel):
    """A reference to a device within an HCL project — not its runtime state."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(description="Owning project ID")
    device_id: int = Field(description="Numeric device ID within the project")
    name: str = Field(description="Device name (e.g. 'S6850_1')")
    model: str | None = Field(default=None, description="Device model (e.g. 'S6850', 'MSR36-20')")
    comware_version: str | None = Field(default=None, description="Comware version string")
    config_path: str | None = Field(default=None, description="Relative path to config snapshot")
    category: str | None = Field(default=None, description="Device category (router, switch, firewall, etc.)")

    def __repr__(self) -> str:
        return f"DeviceRef(project={self.project_id!r}, id={self.device_id}, name={self.name!r})"


class InterfaceRef(BaseModel):
    """A reference to a device interface."""

    model_config = ConfigDict(frozen=True)

    device_id: int = Field(description="Owning device ID")
    name: str = Field(description="Interface name (e.g. 'GigabitEthernet1/0/1')")
    index: str | None = Field(default=None, description="SNMP ifIndex")
    description: str | None = Field(default=None, description="Interface description")

    def __repr__(self) -> str:
        return f"InterfaceRef(device={self.device_id}, name={self.name!r})"


class Link(BaseModel):
    """A link between two device interfaces in a topology."""

    model_config = ConfigDict(frozen=True)

    local_device_id: int = Field(description="Local device ID")
    local_interface: str = Field(description="Local interface name")
    remote_device_id: int = Field(description="Remote device ID")
    remote_interface: str = Field(description="Remote interface name")
    link_type: str | None = Field(default=None, description="Link type (e.g. 'ethernet', 'serial')")

    def __repr__(self) -> str:
        return (
            f"Link({self.local_device_id}:{self.local_interface}"
            f" -> {self.remote_device_id}:{self.remote_interface})"
        )


class Topology(BaseModel):
    """Full topology of an HCL project."""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(description="Project ID")
    devices: list[DeviceRef] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Integrity warnings (e.g. dangling links)")

    def get_device(self, device_id: int) -> DeviceRef | None:
        for d in self.devices:
            if d.device_id == device_id:
                return d
        return None

    def get_device_by_name(self, name: str) -> DeviceRef | None:
        for d in self.devices:
            if d.name == name:
                return d
        return None

    def get_links_for_device(self, device_id: int) -> list[Link]:
        return [l for l in self.links if l.local_device_id == device_id or l.remote_device_id == device_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "devices": [d.model_dump() for d in self.devices],
            "links": [l.model_dump() for l in self.links],
            "warnings": self.warnings,
        }
