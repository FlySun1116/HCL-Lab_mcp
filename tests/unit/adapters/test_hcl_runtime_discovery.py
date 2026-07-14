"""Tests for HCL runtime discovery adapter."""

from __future__ import annotations

import pytest

from h3c_hcl_mcp.adapters.hcl.runtime_discovery import HCLRuntimeDiscovery
from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode


class TestHCLRuntimeDiscovery:
    """Tests for HCLRuntimeDiscovery."""

    @pytest.fixture
    def discovery(self) -> HCLRuntimeDiscovery:
        return HCLRuntimeDiscovery()

    @pytest.fixture
    def configured_discovery(self) -> HCLRuntimeDiscovery:
        disc = HCLRuntimeDiscovery()
        ep = disc.make_console_endpoint(port=5001)
        disc.set_device_state("proj_001", 1, DeviceState.RUNNING, [ep])
        ep2 = disc.make_console_endpoint(port=5002)
        disc.set_device_state("proj_001", 2, DeviceState.RUNNING, [ep2])
        disc.set_device_state("proj_001", 3, DeviceState.STOPPED, [])
        return disc

    @pytest.mark.asyncio
    async def test_discover_project_returns_running_devices(self, configured_discovery: HCLRuntimeDiscovery):
        results = await configured_discovery.discover_project("proj_001")
        assert len(results) == 3

        running = [r for r in results if r.state == DeviceState.RUNNING]
        stopped = [r for r in results if r.state == DeviceState.STOPPED]
        assert len(running) == 2
        assert len(stopped) == 1

    @pytest.mark.asyncio
    async def test_discover_project_empty(self, discovery: HCLRuntimeDiscovery):
        results = await discovery.discover_project("unknown_project")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_discover_device_found(self, configured_discovery: HCLRuntimeDiscovery):
        runtime = await configured_discovery.discover_device("proj_001", 1)
        assert runtime.device_id == 1
        assert runtime.state == DeviceState.RUNNING
        assert runtime.is_running
        assert runtime.console_available
        assert len(runtime.endpoints) == 1
        assert runtime.endpoints[0].port == 5001

    @pytest.mark.asyncio
    async def test_discover_device_not_found(self, discovery: HCLRuntimeDiscovery):
        with pytest.raises(DomainError) as exc:
            await discovery.discover_device("proj_001", 999)
        assert exc.value.code == ErrorCode.DEVICE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_discover_stopped_device(self, configured_discovery: HCLRuntimeDiscovery):
        runtime = await configured_discovery.discover_device("proj_001", 3)
        assert runtime.state == DeviceState.STOPPED
        assert not runtime.is_running
        assert not runtime.console_available

    def test_set_and_remove_device_state(self, discovery: HCLRuntimeDiscovery):
        ep = discovery.make_console_endpoint(port=6001)
        discovery.set_device_state("proj_x", 10, DeviceState.RUNNING, [ep])

        discovery.remove_device_state("proj_x", 10)

        # Now discovering it should return nothing
        import asyncio

        results = asyncio.run(discovery.discover_project("proj_x"))
        assert len([r for r in results if r.device_id == 10]) == 0

    def test_make_console_endpoint(self, discovery: HCLRuntimeDiscovery):
        ep = discovery.make_console_endpoint(port=5000)
        assert ep.transport == TransportType.CONSOLE_TELNET
        assert ep.host == "127.0.0.1"
        assert ep.port == 5000
        assert ep.source == DiscoverySource.CONFIG
        assert ep.confidence == 1.0

    def test_make_console_endpoint_custom(self, discovery: HCLRuntimeDiscovery):
        ep = discovery.make_console_endpoint(
            port=6000,
            host="192.168.1.1",
            confidence=0.5,
            source=DiscoverySource.LOG,
        )
        assert ep.host == "192.168.1.1"
        assert ep.port == 6000
        assert ep.confidence == 0.5
        assert ep.source == DiscoverySource.LOG

    def test_make_ssh_endpoint(self, discovery: HCLRuntimeDiscovery):
        ep = discovery.make_ssh_endpoint()
        assert ep.transport == TransportType.SSH
        assert ep.host == "127.0.0.1"
        assert ep.port == 22
        assert ep.confidence == 0.8

    def test_make_ssh_endpoint_custom(self, discovery: HCLRuntimeDiscovery):
        ep = discovery.make_ssh_endpoint(host="10.0.0.1", port=2222, confidence=0.9)
        assert ep.host == "10.0.0.1"
        assert ep.port == 2222
        assert ep.confidence == 0.9


class TestDeviceRuntime:
    """Tests for DeviceRuntime domain model behavior."""

    def test_best_endpoint_console_first(self):
        ep_telnet = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            host="127.0.0.1",
            port=5001,
            source=DiscoverySource.CONFIG,
            confidence=1.0,
        )
        ep_ssh = RuntimeEndpoint(
            transport=TransportType.SSH,
            host="127.0.0.1",
            port=22,
            source=DiscoverySource.CONFIG,
            confidence=0.8,
        )
        runtime = DeviceRuntime(
            device_id=1,
            device_name="Test",
            state=DeviceState.RUNNING,
            endpoints=[ep_ssh, ep_telnet],
        )

        best = runtime.best_endpoint()
        assert best is not None
        assert best.transport == TransportType.CONSOLE_TELNET

    def test_best_endpoint_fallback(self):
        ep_ssh = RuntimeEndpoint(
            transport=TransportType.SSH,
            host="127.0.0.1",
            port=22,
            source=DiscoverySource.CONFIG,
            confidence=0.8,
        )
        runtime = DeviceRuntime(
            device_id=1,
            device_name="Test",
            state=DeviceState.RUNNING,
            endpoints=[ep_ssh],
        )

        best = runtime.best_endpoint()
        assert best is not None
        assert best.transport == TransportType.SSH

    def test_best_endpoint_no_endpoints(self):
        runtime = DeviceRuntime(
            device_id=1,
            device_name="Test",
            state=DeviceState.STOPPED,
            endpoints=[],
        )
        assert runtime.best_endpoint() is None

    def test_best_endpoint_custom_preference(self):
        ep_telnet = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            host="127.0.0.1",
            port=5001,
            source=DiscoverySource.CONFIG,
            confidence=1.0,
        )
        ep_ssh = RuntimeEndpoint(
            transport=TransportType.SSH,
            host="127.0.0.1",
            port=22,
            source=DiscoverySource.CONFIG,
            confidence=0.8,
        )
        runtime = DeviceRuntime(
            device_id=1,
            device_name="Test",
            state=DeviceState.RUNNING,
            endpoints=[ep_telnet, ep_ssh],
        )

        # Prefer SSH over console
        best = runtime.best_endpoint(preferred=[TransportType.SSH, TransportType.CONSOLE_TELNET])
        assert best is not None
        assert best.transport == TransportType.SSH
