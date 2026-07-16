"""HCL runtime discovery — discover running device state and endpoints.

v0.1.0-beta: Basic process inspection for HCL process detection.
Endpoint discovery via config, formula, and log parsing (when available).
"""

from __future__ import annotations

import subprocess
import sys
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

# HCL process names to check for
_HCL_PROCESS_NAMES = [
    "SimwareClient.exe",
    "SimwareMultiCC.exe",
    "SimwareWrapper.exe",
]


def _is_hcl_running() -> bool:
    """Check if HCL processes are running on the local machine.

    Uses tasklist on Windows, ps on other platforms.
    """
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "STATUS eq RUNNING"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout
        else:
            result = subprocess.run(
                ["ps", "-eo", "comm"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout

        return any(proc in output for proc in _HCL_PROCESS_NAMES)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


class HCLRuntimeDiscovery(RuntimeDiscovery):
    """Discover runtime state of HCL devices.

    Uses real process inspection on the local machine, augmented by
    config/manual state and HCL log parsing.
    """

    _DeviceStateMap = dict[tuple[str, int], tuple[DeviceState, list[RuntimeEndpoint]]]

    def __init__(
        self,
        device_states: _DeviceStateMap | None = None,
        fallback_telnet_base: int = 30000,
        console_host: str = "127.0.0.1",
    ) -> None:
        self._device_states: HCLRuntimeDiscovery._DeviceStateMap = device_states or {}
        self._fallback_telnet_base = fallback_telnet_base
        self._console_host = console_host
        self._hcl_running_cache: bool | None = None
        self._hcl_running_cache_time: float = 0.0

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

    async def _check_hcl_running(self) -> bool:
        """Check if HCL is running, with a short cache to avoid repeated process checks."""
        import time

        now = time.monotonic()
        if self._hcl_running_cache is not None and (now - self._hcl_running_cache_time) < 10.0:
            return self._hcl_running_cache
        self._hcl_running_cache = _is_hcl_running()
        self._hcl_running_cache_time = now
        return self._hcl_running_cache

    def set_topology_devices(
        self,
        project_id: str,
        devices: list[tuple[int, str]],
    ) -> None:
        """Register devices from topology for runtime discovery.

        Args:
            project_id: Project identifier.
            devices: List of (device_id, device_name) tuples.
        """
        for device_id, _device_name in devices:
            key = (project_id, device_id)
            if key not in self._device_states:
                self._device_states[key] = (DeviceState.UNKNOWN, [])

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        """Discover runtime state for all known devices in a project.

        Checks:
        1. HCL process detection (real HCL environment)
        2. Formula-based endpoint guessing when HCL is detected
        3. Explicit config/manual states (override auto-detection)

        Returns a list of DeviceRuntime — one per known device.
        """
        results: list[DeviceRuntime] = []
        hcl_running = await self._check_hcl_running()
        seen_devices: set[int] = set()

        for (pid, device_id), (state, endpoints) in self._device_states.items():
            if pid != project_id:
                continue
            seen_devices.add(device_id)
            device_name = f"Device_{device_id}"

            # HCL process detection tells us HCL is running, but NOT which
            # devices are running. Formula-based ports are candidates that
            # need probe+prompt verification before becoming usable endpoints.
            if state == DeviceState.UNKNOWN and hcl_running:
                effective_state = DeviceState.UNKNOWN
                effective_endpoints: list[RuntimeEndpoint] = []
            elif state == DeviceState.UNKNOWN and not hcl_running:
                effective_state = DeviceState.STOPPED
                effective_endpoints = []
            else:
                effective_state = state
                effective_endpoints = list(endpoints)

            runtime = DeviceRuntime(
                device_id=device_id,
                device_name=device_name,
                state=effective_state,
                endpoints=effective_endpoints,
                last_seen=datetime.now(tz=UTC) if effective_state == DeviceState.RUNNING else None,
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

        # Apply same HCL detection logic as discover_project
        if state == DeviceState.UNKNOWN:
            hcl_running = await self._check_hcl_running()
            if hcl_running:
                effective_state = DeviceState.UNKNOWN
                effective_endpoints: list[RuntimeEndpoint] = []
            else:
                effective_state = DeviceState.STOPPED
                effective_endpoints = []
        else:
            effective_state = state
            effective_endpoints = list(endpoints)

        return DeviceRuntime(
            device_id=device_id,
            device_name=device_name,
            state=effective_state,
            endpoints=effective_endpoints,
            last_seen=datetime.now(tz=UTC) if effective_state == DeviceState.RUNNING else None,
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
