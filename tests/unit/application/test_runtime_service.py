"""Tests for project-aware runtime application orchestration."""

from __future__ import annotations

from h3c_hcl_mcp.application.runtime_service import ProjectAwareRuntimeDiscovery
from h3c_hcl_mcp.domain.device import DeviceRuntime, DeviceState
from h3c_hcl_mcp.domain.project import DeviceRef, LabProject, Topology
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery


class _ProjectRepository(ProjectRepository):
    def __init__(self, topology: Topology) -> None:
        self.topology = topology

    async def list_projects(self, query=None, limit=50, cursor=None):
        del query, limit, cursor
        return [], None

    async def get_project(self, project_id: str) -> LabProject:
        return LabProject(project_id=project_id, name=project_id, path=project_id)

    async def get_topology(self, project_id: str) -> Topology:
        assert project_id == self.topology.project_id
        return self.topology


class _Runtime(RuntimeDiscovery):
    def __init__(self) -> None:
        self.devices: dict[tuple[str, int], str] = {}

    def set_topology(self, topology: Topology) -> None:
        self.devices = {(topology.project_id, device.device_id): device.name for device in topology.devices}

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        return [
            DeviceRuntime(device_id=device_id, device_name=name, state=DeviceState.UNKNOWN)
            for (registered_project, device_id), name in self.devices.items()
            if registered_project == project_id
        ]

    async def discover_device(self, project_id: str, device_id: int) -> DeviceRuntime:
        return DeviceRuntime(
            device_id=device_id,
            device_name=self.devices[(project_id, device_id)],
            state=DeviceState.UNKNOWN,
        )


async def test_direct_device_discovery_registers_topology_first() -> None:
    topology = Topology(
        project_id="lab",
        devices=[DeviceRef(project_id="lab", device_id=7, name="S6850_7")],
    )
    repository = _ProjectRepository(topology)
    runtime = _Runtime()
    service = ProjectAwareRuntimeDiscovery(repository, runtime, runtime)

    discovered = await service.discover_device("lab", 7)

    assert discovered.device_name == "S6850_7"
