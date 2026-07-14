"""Port: RuntimeDiscovery — discover running devices and their endpoints."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3c_hcl_mcp.domain.device import DeviceRuntime


class RuntimeDiscovery(ABC):
    """Discover runtime state and connectivity of HCL devices.

    Implementations may inspect HCL processes, parse logs, probe loopback ports,
    or use future official HCL APIs.
    """

    @abstractmethod
    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        """Discover runtime state for all devices in a project.

        Returns a list of DeviceRuntime — one entry per device in the project.
        Devices that are not running will have state=STOPPED and no endpoints.
        """
        ...

    @abstractmethod
    async def discover_device(
        self,
        project_id: str,
        device_id: int,
    ) -> DeviceRuntime:
        """Discover runtime state for a specific device.

        Raises:
            DomainError(DEVICE_NOT_FOUND): device not in project.
        """
        ...
