"""Tests for HCL runtime discovery adapter."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from h3c_hcl_mcp.adapters.hcl.runtime_discovery import (
    HCLRuntimeDiscovery,
    _log_paths_from_install_dir,
    _looks_like_comware_prompt,
    _probe_comware_console,
    _windows_executable_from_registry,
)
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
    async def test_process_inspection_does_not_block_event_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def slow_process_inspection() -> bool:
            time.sleep(0.2)
            return False

        monkeypatch.setattr(
            "h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running",
            slow_process_inspection,
        )
        discovery = HCLRuntimeDiscovery(log_observation=False, cache_ttl_seconds=0)

        started = time.monotonic()
        task = asyncio.create_task(discovery.discover_project("proj_001"))
        await asyncio.sleep(0.02)
        heartbeat_elapsed = time.monotonic() - started
        await task

        assert heartbeat_elapsed < 0.1

    @pytest.mark.asyncio
    async def test_log_loading_does_not_block_event_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        discovery = HCLRuntimeDiscovery(process_inspection=False, cache_ttl_seconds=0)
        original_loader = discovery._load_log_observer

        def slow_log_loader():
            time.sleep(0.2)
            return original_loader()

        monkeypatch.setattr(discovery, "_load_log_observer", slow_log_loader)

        started = time.monotonic()
        task = asyncio.create_task(discovery.discover_project("proj_001"))
        await asyncio.sleep(0.02)
        heartbeat_elapsed = time.monotonic() - started
        await task

        assert heartbeat_elapsed < 0.1

    @pytest.mark.asyncio
    async def test_topology_refresh_removes_deleted_devices(self) -> None:
        discovery = HCLRuntimeDiscovery(process_inspection=False)
        discovery.set_topology_devices("proj_001", [(1, "Old_Device"), (2, "Keep_Device")])

        discovery.set_topology_devices("proj_001", [(2, "Renamed_Device")])

        results = await discovery.discover_project("proj_001")
        assert [(runtime.device_id, runtime.device_name) for runtime in results] == [(2, "Renamed_Device")]
        with pytest.raises(DomainError) as exc:
            await discovery.discover_device("proj_001", 1)
        assert exc.value.code == ErrorCode.DEVICE_NOT_FOUND

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


class TestRealHCLRuntimeDiscovery:
    """Black-box discovery tests using sanitized HCL 5.10.3 log lines."""

    @pytest.fixture
    def active_log(self) -> str:
        return str(Path(__file__).parents[2] / "fixtures" / "hcl_logs" / "hcl_runtime_5103_active.txt")

    @pytest.fixture
    def rebound_log(self) -> str:
        return str(Path(__file__).parents[2] / "fixtures" / "hcl_logs" / "hcl_runtime_5103_rebound.txt")

    def test_explicit_install_dir_discovers_rotated_hcl_logs(self, tmp_path: Path):
        log_dir = tmp_path / "Log" / "HCLLog"
        log_dir.mkdir(parents=True)
        current = log_dir / "HCL.log"
        rotated = log_dir / "HCL.log.2026-07-14.0"
        ignored = log_dir / "other.log"
        for path in (current, rotated, ignored):
            path.write_text("", encoding="utf-8")

        discovered = {Path(path).name for path in _log_paths_from_install_dir(str(tmp_path))}

        assert discovered == {current.name, rotated.name}

    @pytest.mark.parametrize(
        ("registry_value", "expected"),
        [
            (r'"F:\\HCL\\Uninstall.exe",0', r"F:\\HCL\\Uninstall.exe"),
            (r"F:\\HCL\\Uninstall.exe", r"F:\\HCL\\Uninstall.exe"),
            ("", ""),
        ],
    )
    def test_extracts_executable_from_registry(self, registry_value: str, expected: str):
        assert _windows_executable_from_registry(registry_value) == expected

    def test_prompt_detection_accepts_comware_and_telnet_negotiation(self):
        assert _looks_like_comware_prompt(b"\xff\xfb\x01\r\n<H3C>")
        assert _looks_like_comware_prompt(b"\r\n[H3C-GigabitEthernet1/0/1]")
        assert not _looks_like_comware_prompt(b"HTTP/1.1 200 OK\r\n")
        assert not _looks_like_comware_prompt(b"Username:")

    @pytest.mark.asyncio
    async def test_default_probe_requires_a_comware_prompt(self):
        async def serve_prompt(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            del reader
            try:
                writer.write(b"\xff\xfb\x01\r\n<H3C>")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(serve_prompt, "127.0.0.1", 0)
        try:
            socket = server.sockets[0]
            port = int(socket.getsockname()[1])
            assert await _probe_comware_console("127.0.0.1", port, 1.0)
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_explicit_log_mapping_and_verified_probe_becomes_running(
        self, active_log: str, monkeypatch: pytest.MonkeyPatch
    ):
        async def verified_probe(host: str, port: int, timeout: float) -> bool:
            return host == "127.0.0.1" and port == 30001 and timeout > 0

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[active_log], console_probe=verified_probe)
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_sample_real", 1)

        assert runtime.device_name == "S6850_1"
        assert runtime.state == DeviceState.RUNNING
        assert runtime.endpoints[0].port == 30001
        assert runtime.endpoints[0].source == DiscoverySource.PROBE
        assert runtime.endpoints[0].extra["project_id"] == "hcl_sample_real"
        assert runtime.endpoints[0].extra["device_id"] == "1"

    @pytest.mark.asyncio
    async def test_process_inspection_can_be_disabled_without_skipping_probe(
        self, active_log: str, monkeypatch: pytest.MonkeyPatch
    ):
        def unexpected_process_check() -> bool:
            raise AssertionError("process inspection should be disabled")

        async def verified_probe(host: str, port: int, timeout: float) -> bool:
            return host == "127.0.0.1" and port == 30001 and timeout > 0

        monkeypatch.setattr(
            "h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running",
            unexpected_process_check,
        )
        discovery = HCLRuntimeDiscovery(
            log_paths=[active_log],
            process_inspection=False,
            console_probe=verified_probe,
        )
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_sample_real", 1)

        assert runtime.state == DeviceState.RUNNING

    @pytest.mark.asyncio
    async def test_closed_port_never_becomes_running(self, active_log: str, monkeypatch: pytest.MonkeyPatch):
        async def closed_probe(host: str, port: int, timeout: float) -> bool:
            return False

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[active_log], console_probe=closed_probe)
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_sample_real", 1)

        assert runtime.state == DeviceState.UNKNOWN
        assert runtime.endpoints == []

    @pytest.mark.asyncio
    async def test_alias_rebind_prevents_historical_endpoint_reuse(
        self, rebound_log: str, monkeypatch: pytest.MonkeyPatch
    ):
        probe_calls: list[int] = []

        async def probe(host: str, port: int, timeout: float) -> bool:
            probe_calls.append(port)
            return True

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[rebound_log], console_probe=probe)
        discovery.set_topology_devices("hcl_old", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_old", 1)

        assert runtime.state == DeviceState.STOPPED
        assert runtime.endpoints == []
        assert probe_calls == []

    @pytest.mark.asyncio
    async def test_formula_alone_never_creates_an_endpoint(self, monkeypatch: pytest.MonkeyPatch):
        probe_calls: list[int] = []

        async def probe(host: str, port: int, timeout: float) -> bool:
            probe_calls.append(port)
            return True

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(fallback_telnet_base=30000, console_probe=probe)
        discovery.set_topology_devices("project_without_log", [(1, "S6850_1")])

        runtime = await discovery.discover_device("project_without_log", 1)

        assert runtime.state == DeviceState.UNKNOWN
        assert runtime.endpoints == []
        assert probe_calls == []

    @pytest.mark.asyncio
    async def test_log_observation_can_be_disabled(self, active_log: str, monkeypatch: pytest.MonkeyPatch):
        probe_calls: list[int] = []

        async def probe(host: str, port: int, timeout: float) -> bool:
            probe_calls.append(port)
            return True

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[active_log], log_observation=False, console_probe=probe)
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_sample_real", 1)

        assert runtime.state == DeviceState.UNKNOWN
        assert probe_calls == []

    @pytest.mark.asyncio
    async def test_loopback_probe_can_be_disabled(self, active_log: str, monkeypatch: pytest.MonkeyPatch):
        probe_calls: list[int] = []

        async def probe(host: str, port: int, timeout: float) -> bool:
            probe_calls.append(port)
            return True

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[active_log], loopback_probe=False, console_probe=probe)
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1")])

        runtime = await discovery.discover_device("hcl_sample_real", 1)

        assert runtime.state == DeviceState.UNKNOWN
        assert runtime.endpoints == []
        assert probe_calls == []

    @pytest.mark.asyncio
    async def test_max_probe_ports_is_enforced(self, active_log: str, monkeypatch: pytest.MonkeyPatch):
        probe_calls: list[int] = []

        async def probe(host: str, port: int, timeout: float) -> bool:
            probe_calls.append(port)
            return True

        monkeypatch.setattr("h3c_hcl_mcp.adapters.hcl.runtime_discovery._is_hcl_running", lambda: True)
        discovery = HCLRuntimeDiscovery(log_paths=[active_log], max_probe_ports=1, console_probe=probe)
        discovery.set_topology_devices("hcl_sample_real", [(1, "S6850_1"), (2, "S6850_2")])

        runtimes = await discovery.discover_project("hcl_sample_real")

        assert probe_calls == [30001]
        assert [runtime.state for runtime in runtimes] == [DeviceState.RUNNING, DeviceState.UNKNOWN]


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
