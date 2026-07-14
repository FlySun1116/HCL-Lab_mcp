"""HCL runtime discovery — discover running device state and endpoints.

v0.1: Uses configurable static device state (synthetic/manual).
Future: Real HCL process inspection, log parsing, and loopback port probing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery


class HCLRuntimeDiscovery(RuntimeDiscovery):
    """Discover runtime state of HCL devices.

    In v0.1, device state is provided via configuration (synthetic/manual).
    Real HCL process inspection and log parsing will be added in v0.1.0-beta.

    Args:
        device_states: Optional dict mapping (project_id, device_id) to
                       (DeviceState, list of RuntimeEndpoint).
    """

    _DeviceStateMap = dict[tuple[str, int], tuple[DeviceState, list[RuntimeEndpoint]]]

    def __init__(
        self,
        device_states: _DeviceStateMap | None = None,
    ) -> None:
        self._device_states: HCLRuntimeDiscovery._DeviceStateMap = device_states or {}

    def set_device_state(
        self,
        project_id: str,
        device_id: int,
        state: DeviceState,
        endpoints: list[RuntimeEndpoint] | None = None,
    ) -> None:
        """Configure the synthetic state for a device."""
        key = (project_id, device_id)
        self._device_states[key] = (state, endpoints or [])

    def remove_device_state(self, project_id: str, device_id: int) -> None:
        """Remove synthetic state for a device."""
        key = (project_id, device_id)
        self._device_states.pop(key, None)

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        """Discover runtime state for all configured devices in a project.

        Returns a list of DeviceRuntime — one per known device.
        Devices not explicitly configured will be returned as UNKNOWN/STOPPED
        with no endpoints.
        """
        results: list[DeviceRuntime] = []

        for (pid, device_id), (state, endpoints) in self._device_states.items():
            if pid != project_id:
                continue

            device_name = f"Device_{device_id}"

            runtime = DeviceRuntime(
                device_id=device_id,
                device_name=device_name,
                state=state,
                endpoints=list(endpoints),
                last_seen=datetime.now(tz=UTC) if state == DeviceState.RUNNING else None,
            )
            results.append(runtime)

        return results

    async def discover_device(
        self,
        project_id: str,
        device_id: int,
    ) -> DeviceRuntime:
        """Discover runtime state for a specific device.

        Raises:
            DomainError(DEVICE_NOT_FOUND): device not configured.
        """
        key = (project_id, device_id)

        if key not in self._device_states:
            raise DomainError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"Device {device_id} not found in project {project_id!r}",
                details={"project_id": project_id, "device_id": device_id},
            )

        state, endpoints = self._device_states[key]
        device_name = f"Device_{device_id}"

        return DeviceRuntime(
            device_id=device_id,
            device_name=device_name,
            state=state,
            endpoints=list(endpoints),
            last_seen=datetime.now(tz=UTC) if state == DeviceState.RUNNING else None,
        )

    # ------------------------------------------------------------------
    # Convenience factory for building synthetic RuntimeEndpoint lists
    # ------------------------------------------------------------------

    @staticmethod
    def make_console_endpoint(
        port: int,
        host: str = "127.0.0.1",
        confidence: float = 1.0,
        source: DiscoverySource = DiscoverySource.CONFIG,
    ) -> RuntimeEndpoint:
        """Create a CONSOLE_TELNET RuntimeEndpoint."""
        return RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            host=host,
            port=port,
            source=source,
            confidence=confidence,
            discovered_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def make_ssh_endpoint(
        host: str = "127.0.0.1",
        port: int = 22,
        confidence: float = 0.8,
        source: DiscoverySource = DiscoverySource.CONFIG,
    ) -> RuntimeEndpoint:
        """Create an SSH RuntimeEndpoint."""
        return RuntimeEndpoint(
            transport=TransportType.SSH,
            host=host,
            port=port,
            source=source,
            confidence=confidence,
            discovered_at=datetime.now(tz=UTC),
        )
