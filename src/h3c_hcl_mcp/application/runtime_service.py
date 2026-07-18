"""Application orchestration for project-aware runtime discovery."""

from __future__ import annotations

from typing import Protocol

from h3c_hcl_mcp.domain.device import DeviceRuntime
from h3c_hcl_mcp.domain.project import Topology
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery


class TopologyRegistrar(Protocol):
    """Internal capability used to give an adapter authoritative topology."""

    def set_topology(self, topology: Topology) -> None:
        """Register current project devices without inferring endpoints."""
        ...


class ProjectAwareRuntimeDiscovery(RuntimeDiscovery):
    """Ensure runtime discovery always has authoritative project topology.

    MCP callers may invoke a device command before any project/runtime listing.
    This application service removes that call-order dependency while keeping
    filesystem access in ProjectRepository and endpoint discovery in the
    RuntimeDiscovery adapter.
    """

    def __init__(
        self,
        project_repository: ProjectRepository,
        delegate: RuntimeDiscovery,
        topology_registrar: TopologyRegistrar,
    ) -> None:
        self._project_repository = project_repository
        self._delegate = delegate
        self._topology_registrar = topology_registrar

    async def _register_project(self, project_id: str) -> None:
        topology = await self._project_repository.get_topology(project_id)
        self._topology_registrar.set_topology(topology)

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        await self._register_project(project_id)
        return await self._delegate.discover_project(project_id)

    async def discover_device(self, project_id: str, device_id: int) -> DeviceRuntime:
        await self._register_project(project_id)
        return await self._delegate.discover_device(project_id, device_id)
