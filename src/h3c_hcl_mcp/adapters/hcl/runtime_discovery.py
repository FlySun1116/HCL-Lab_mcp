"""Safe HCL runtime and loopback console discovery.

HCL process presence is only a health signal.  Device endpoints originate
from explicit project/console mappings in HCL's ordinary text logs and are
published only after a bounded loopback Telnet/Comware prompt probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import ntpath
import os
import re
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from h3c_hcl_mcp.adapters.hcl.log_observer import LogObserver
from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import Topology
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery

_HCL_PROCESS_NAMES = [
    "SimwareClient.exe",
    "SimwareMultiCC.exe",
    "SimwareWrapper.exe",
]

ConsoleProbe = Callable[[str, int, float], Awaitable[bool]]

_COMWARE_PROMPT = re.compile(r"(?:^|[\r\n])\s*(?:<[^<>\[\]\r\n]{1,64}>|\[[^<>\[\]\r\n]{1,64}\])\s*$")


def _is_hcl_running() -> bool:
    """Check whether the public HCL desktop processes are present."""
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
        return any(process_name in output for process_name in _HCL_PROCESS_NAMES)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _strip_telnet_control(payload: bytes) -> str:
    """Remove common Telnet negotiation bytes before prompt matching."""
    clean = bytearray()
    index = 0
    while index < len(payload):
        byte = payload[index]
        if byte != 255:  # IAC
            if byte != 0:
                clean.append(byte)
            index += 1
            continue
        if index + 1 >= len(payload):
            break
        command = payload[index + 1]
        if command in (251, 252, 253, 254):  # WILL/WONT/DO/DONT + option
            index += 3
        elif command == 250:  # SB ... IAC SE
            end = payload.find(b"\xff\xf0", index + 2)
            index = len(payload) if end < 0 else end + 2
        else:
            index += 2
    return clean.decode("utf-8", errors="ignore")


def _telnet_refusal_response(payload: bytes) -> bytes:
    """Build conservative DONT/WONT replies for Telnet option requests."""
    response = bytearray()
    index = 0
    while index + 2 < len(payload):
        if payload[index] != 255:
            index += 1
            continue
        command = payload[index + 1]
        option = payload[index + 2]
        if command in (251, 252):  # WILL/WONT -> DONT
            response.extend((255, 254, option))
            index += 3
        elif command in (253, 254):  # DO/DONT -> WONT
            response.extend((255, 252, option))
            index += 3
        else:
            index += 2
    return bytes(response)


def _looks_like_comware_prompt(payload: bytes) -> bool:
    text = _strip_telnet_control(payload)
    return bool(_COMWARE_PROMPT.search(text))


async def _probe_comware_console(host: str, port: int, timeout: float) -> bool:
    """Probe one explicit loopback candidate without executing a CLI command.

    The probe performs Telnet option refusal and may send one empty CRLF solely
    to elicit the current prompt.  Login/password prompts are never answered.
    """
    if not _is_loopback_host(host) or not 1 <= port <= 65535:
        return False

    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        assert writer is not None
        payload = bytearray()
        deadline = time.monotonic() + timeout
        sent_empty_line = False

        while time.monotonic() < deadline and len(payload) < 16384:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=min(0.25, remaining))
            except TimeoutError:
                chunk = b""

            if chunk:
                payload.extend(chunk)
                response = _telnet_refusal_response(chunk)
                if response:
                    writer.write(response)
                    await writer.drain()
                if _looks_like_comware_prompt(bytes(payload)):
                    return True
                lowered = _strip_telnet_control(bytes(payload)).casefold()
                if "password:" in lowered or "login:" in lowered or "username:" in lowered:
                    return False
            elif not sent_empty_line:
                writer.write(b"\r\n")
                await writer.drain()
                sent_empty_line = True
            elif reader.at_eof():
                break

        return _looks_like_comware_prompt(bytes(payload))
    except (OSError, TimeoutError):
        return False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await writer.wait_closed()


def _log_paths_from_install_dir(install_dir: str | None) -> list[str]:
    """Find HCL main text logs without querying any HCL control service."""
    configured_dir = install_dir or os.environ.get("H3C_HCL_MCP__HCL__INSTALL_DIR")
    candidates = [configured_dir] if configured_dir else _auto_detect_hcl_install_dirs()
    for candidate in candidates:
        if not candidate:
            continue
        log_dir = Path(os.path.expandvars(candidate)).expanduser() / "Log" / "HCLLog"
        try:
            paths = [str(path) for path in log_dir.glob("HCL.log*") if path.is_file()]
        except OSError:
            continue
        if paths:
            return paths
    return []


def _auto_detect_hcl_install_dirs() -> list[str]:
    """Return public OS-level HCL install candidates in priority order."""
    candidates: list[str] = []
    for environment_name in ("HCL_HOME", "H3C_HCL_HOME"):
        value = os.environ.get(environment_name)
        if value:
            candidates.append(value)

    candidates.extend(_windows_registry_install_dirs())
    for environment_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(environment_name)
        if base:
            candidates.append(str(Path(base) / "HCL"))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = os.path.normcase(os.path.abspath(os.path.expandvars(candidate)))
        if identity not in seen:
            seen.add(identity)
            unique.append(candidate)
    return unique


def _windows_registry_install_dirs() -> list[str]:
    """Read HCL uninstall metadata from the standard Windows registry."""
    if sys.platform != "win32":
        return []

    try:
        import winreg
    except ImportError:
        return []

    uninstall_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    candidates: list[str] = []

    for root in roots:
        for view in views:
            try:
                parent = winreg.OpenKey(root, uninstall_key, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with parent:
                subkey_count = winreg.QueryInfoKey(parent)[0]
                for index in range(subkey_count):
                    try:
                        subkey_name = winreg.EnumKey(parent, index)
                        product = winreg.OpenKey(parent, subkey_name)
                    except OSError:
                        continue
                    with product:
                        try:
                            display_name = str(winreg.QueryValueEx(product, "DisplayName")[0])
                        except OSError:
                            continue
                        if not re.fullmatch(r"HCL\s+5\.10(?:\.\d+)?", display_name.strip(), re.IGNORECASE):
                            continue

                        install_location = _registry_string(product, "InstallLocation")
                        if install_location:
                            candidates.append(install_location)
                            continue
                        display_icon = _registry_string(product, "DisplayIcon")
                        executable = _windows_executable_from_registry(display_icon)
                        if executable:
                            candidates.append(ntpath.dirname(executable))
    return candidates


def _registry_string(key: object, name: str) -> str:
    try:
        import winreg

        value = winreg.QueryValueEx(key, name)[0]  # type: ignore[arg-type]
    except (ImportError, OSError):
        return ""
    return str(value).strip() if value is not None else ""


def _windows_executable_from_registry(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith('"'):
        closing_quote = raw.find('"', 1)
        return raw[1:closing_quote] if closing_quote > 1 else ""
    return raw.split(",", 1)[0].strip()


class HCLRuntimeDiscovery(RuntimeDiscovery):
    """Discover HCL device runtime state from explicit logs and safe probes."""

    _DeviceStateMap = dict[tuple[str, int], tuple[DeviceState, list[RuntimeEndpoint]]]

    def __init__(
        self,
        device_states: _DeviceStateMap | None = None,
        fallback_telnet_base: int = 30000,
        console_host: str = "127.0.0.1",
        *,
        log_paths: list[str] | None = None,
        install_dir: str | None = None,
        process_inspection: bool = True,
        log_observation: bool = True,
        loopback_probe: bool = True,
        max_probe_ports: int = 32,
        probe_timeout_seconds: float = 1.0,
        console_probe: ConsoleProbe | None = None,
        cache_ttl_seconds: float = 2.0,
    ) -> None:
        self._device_states: HCLRuntimeDiscovery._DeviceStateMap = device_states or {}
        self._device_names: dict[tuple[str, int], str] = {}
        # Retained as configuration/API compatibility.  A formula never creates
        # a candidate; only explicit HCL log mappings do.
        self._fallback_telnet_base = fallback_telnet_base
        self._console_host = console_host
        self._log_paths = (
            list(log_paths) if log_paths is not None else _log_paths_from_install_dir(install_dir)
        )
        self._process_inspection = process_inspection
        self._log_observation = log_observation
        self._loopback_probe = loopback_probe
        self._max_probe_ports = max(1, max_probe_ports)
        self._probe_timeout_seconds = max(0.05, probe_timeout_seconds)
        self._console_probe = console_probe or _probe_comware_console
        self._cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._runtime_cache: dict[str, tuple[float, list[DeviceRuntime]]] = {}
        self._hcl_running_cache: bool | None = None
        self._hcl_running_cache_time = 0.0

    def _invalidate(self, project_id: str) -> None:
        self._runtime_cache.pop(project_id, None)

    def set_device_state(
        self,
        project_id: str,
        device_id: int,
        state: DeviceState,
        endpoints: list[RuntimeEndpoint] | None = None,
    ) -> None:
        """Configure an explicit/manual state (primarily tests and adapters)."""
        self._device_states[(project_id, device_id)] = (state, endpoints or [])
        self._invalidate(project_id)

    def remove_device_state(self, project_id: str, device_id: int) -> None:
        key = (project_id, device_id)
        self._device_states.pop(key, None)
        self._device_names.pop(key, None)
        self._invalidate(project_id)

    async def _check_hcl_running(self) -> bool:
        if not self._process_inspection:
            # Endpoint verification remains mandatory. Disabling process
            # inspection only removes the tasklist/ps prerequisite.
            return True
        now = time.monotonic()
        if self._hcl_running_cache is not None and now - self._hcl_running_cache_time < 10.0:
            return self._hcl_running_cache
        # tasklist/ps can block for several seconds on a busy Windows host.
        # Keep the stdio event loop responsive while inspecting processes.
        self._hcl_running_cache = await asyncio.to_thread(_is_hcl_running)
        self._hcl_running_cache_time = now
        return self._hcl_running_cache

    def set_topology_devices(self, project_id: str, devices: list[tuple[int, str]]) -> None:
        """Register authoritative topology IDs/names without guessing endpoints."""
        changed = False
        current_ids = {device_id for device_id, _ in devices}

        # Topology is authoritative.  A project can be edited while the MCP
        # server remains alive, so devices removed from the project must not
        # survive in runtime snapshots or command lookups.
        stale_keys = [
            key for key in self._device_states if key[0] == project_id and key[1] not in current_ids
        ]
        for key in stale_keys:
            self._device_states.pop(key, None)
            self._device_names.pop(key, None)
            changed = True

        for device_id, device_name in devices:
            key = (project_id, device_id)
            if key not in self._device_states:
                self._device_states[key] = (DeviceState.UNKNOWN, [])
                changed = True
            if self._device_names.get(key) != device_name:
                self._device_names[key] = device_name
                changed = True
        if changed:
            self._invalidate(project_id)

    def set_topology(self, topology: Topology) -> None:
        """Register authoritative device IDs and names from a domain topology."""
        self.set_topology_devices(
            topology.project_id,
            [(device.device_id, device.name) for device in topology.devices],
        )

    def _load_log_observer(self) -> LogObserver:
        observer = LogObserver()
        if self._log_observation and self._log_paths:
            observer.load_files(self._log_paths)
        return observer

    async def _discover_uncached(self, project_id: str) -> list[DeviceRuntime]:
        hcl_running = await self._check_hcl_running()
        # Log discovery reads and parses multiple rotated files. It is
        # ordinary blocking filesystem I/O and must not freeze other MCP calls.
        observer = await asyncio.to_thread(self._load_log_observer) if hcl_running else LogObserver()
        candidates = observer.get_project_endpoints(project_id)
        probe_count = 0
        results: list[DeviceRuntime] = []

        project_devices = sorted(
            (
                (device_id, state, endpoints)
                for (pid, device_id), (state, endpoints) in self._device_states.items()
                if pid == project_id
            ),
            key=lambda item: item[0],
        )

        for device_id, state, endpoints in project_devices:
            key = (project_id, device_id)
            device_name = self._device_names.get(key, f"Device_{device_id}")
            effective_state = state
            effective_endpoints = list(endpoints)

            if state == DeviceState.UNKNOWN:
                effective_endpoints = []
                if not hcl_running or observer.is_device_closed(project_id, device_id):
                    effective_state = DeviceState.STOPPED
                else:
                    effective_state = DeviceState.UNKNOWN
                    device_candidates = candidates.get(device_id, [])
                    if (
                        self._loopback_probe
                        and probe_count < self._max_probe_ports
                        and _is_loopback_host(self._console_host)
                    ):
                        for candidate in device_candidates:
                            if probe_count >= self._max_probe_ports:
                                break
                            # Preserve the configured loopback host, but never
                            # probe a non-loopback address from a log candidate.
                            host = self._console_host
                            probe_count += 1
                            try:
                                verified = await self._console_probe(
                                    host, candidate.port, self._probe_timeout_seconds
                                )
                            except Exception:
                                verified = False
                            if verified:
                                extra = dict(candidate.extra)
                                extra["candidate_source"] = candidate.source.value
                                extra["project_id"] = project_id
                                extra["device_id"] = str(device_id)
                                effective_endpoints = [
                                    RuntimeEndpoint(
                                        transport=TransportType.CONSOLE_TELNET,
                                        host=host,
                                        port=candidate.port,
                                        source=DiscoverySource.PROBE,
                                        confidence=1.0,
                                        discovered_at=datetime.now(tz=UTC),
                                        extra=extra,
                                    )
                                ]
                                effective_state = DeviceState.RUNNING
                                break

            results.append(
                DeviceRuntime(
                    device_id=device_id,
                    device_name=device_name,
                    state=effective_state,
                    endpoints=effective_endpoints,
                    last_seen=datetime.now(tz=UTC) if effective_state == DeviceState.RUNNING else None,
                )
            )

        return results

    async def discover_project(self, project_id: str) -> list[DeviceRuntime]:
        """Return one coherent runtime snapshot for all registered devices."""
        now = time.monotonic()
        cached = self._runtime_cache.get(project_id)
        if cached is not None and now - cached[0] < self._cache_ttl_seconds:
            return list(cached[1])
        results = await self._discover_uncached(project_id)
        self._runtime_cache[project_id] = (now, results)
        return list(results)

    async def discover_device(self, project_id: str, device_id: int) -> DeviceRuntime:
        """Return a device from the same project snapshot used by list calls."""
        if (project_id, device_id) not in self._device_states:
            raise DomainError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"Device {device_id} not found in project {project_id!r}",
                details={"project_id": project_id, "device_id": device_id},
            )
        for runtime in await self.discover_project(project_id):
            if runtime.device_id == device_id:
                return runtime
        raise DomainError(
            code=ErrorCode.DEVICE_NOT_FOUND,
            message=f"Device {device_id} not found in project {project_id!r}",
            details={"project_id": project_id, "device_id": device_id},
        )

    @staticmethod
    def make_console_endpoint(
        port: int,
        host: str = "127.0.0.1",
        confidence: float = 1.0,
        source: DiscoverySource = DiscoverySource.CONFIG,
    ) -> RuntimeEndpoint:
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
        return RuntimeEndpoint(
            transport=TransportType.SSH,
            host=host,
            port=port,
            source=source,
            confidence=confidence,
            discovered_at=datetime.now(tz=UTC),
        )
