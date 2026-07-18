"""Tools for read-only H3C Comware device interaction.

All tools in this module are read-only and use display/diagnostic commands only.
Write operations are deferred to v0.2+.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from h3c_hcl_mcp.domain.command import CommandRequest, CommandTarget, CommandType
from h3c_hcl_mcp.domain.device import TransportType
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.infrastructure.audit.redact import redact_sensitive
from h3c_hcl_mcp.infrastructure.settings import DeviceSettings, ServerSettings
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.command_parser import CommandParser
from h3c_hcl_mcp.ports.device_transport import DeviceTransport
from h3c_hcl_mcp.ports.policy_engine import PolicyEngine
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery

_DESTINATION_PATTERN = r"^[A-Za-z0-9:.][A-Za-z0-9._:-]{0,252}$"
SafeDestination = Annotated[
    str,
    Field(
        min_length=1,
        max_length=253,
        pattern=_DESTINATION_PATTERN,
        description="IPv4, IPv6, or hostname without whitespace or CLI options",
    ),
]
ProjectId = Annotated[str, Field(min_length=1, max_length=256, description="HCL project identifier")]
DeviceId = Annotated[int, Field(ge=0, le=2_147_483_647, description="HCL device identifier")]
DisplayCommand = Annotated[
    str,
    Field(min_length=1, max_length=1024, description="One read-only Comware command line"),
]
CandidateConfig = Annotated[
    str,
    Field(max_length=65_536, description="Candidate configuration text reserved for v0.2"),
]


def _is_comware_candidate(model: str | None, category: str | None, version: str | None) -> bool:
    """Exclude HCL terminal nodes from H3C/Comware tool results."""
    normalized_model = (model or "").strip().casefold()
    normalized_category = (category or "").strip().casefold()
    normalized_version = (version or "").strip().casefold()
    if "cmw" in normalized_version or "comware" in normalized_version:
        return True
    if normalized_model in {"pc", "host", "vpc"}:
        return False
    return normalized_category not in {"终端", "terminal", "host", "pc"}


def _classify_read_only_command(command: str) -> CommandType:
    """Map a read-only CLI command to the policy category it must use."""
    parts = command.lstrip().split(maxsplit=1)
    if parts and parts[0].casefold() in {"ping", "tracert"}:
        return CommandType.DIAGNOSTIC
    return CommandType.DISPLAY


def _public_parsed_data(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Remove parser-internal raw copies before returning MCP content."""
    public = {key: value for key, value in parsed.items() if key not in {"_raw", "raw"}}
    return public or None


def register(mcp: FastMCP, **deps: Any) -> None:
    """Register H3C read-only tools on the MCP server.

    Args:
        mcp: The FastMCP server instance.
        **deps: Port implementations injected by the Composition Root.
    """
    project_repo: ProjectRepository = deps["project_repository"]
    runtime_disc: RuntimeDiscovery = deps["runtime_discovery"]
    transport: DeviceTransport = deps["device_transport"]
    parser: CommandParser = deps["command_parser"]
    policy: PolicyEngine = deps["policy_engine"]
    server_settings: ServerSettings = deps["server_settings"]
    device_settings: DeviceSettings = deps["device_settings"]
    default_command_timeout = min(
        device_settings.command_timeout_seconds,
        server_settings.max_tool_seconds,
        120,
    )
    preferred_transports = [TransportType(item) for item in device_settings.preferred_transports]

    async def _resolve_runtime_endpoint(project_id: str, device_id: int) -> Any:
        """Resolve the runtime endpoint for a device.

        Returns (device_runtime, device_name).
        """
        runtime = await runtime_disc.discover_device(project_id, device_id)
        if not runtime.is_running:
            raise DomainError(
                code=ErrorCode.DEVICE_NOT_RUNNING,
                message=f"Device {device_id} is not running (state: {runtime.state.value})",
            )

        return runtime

    async def _execute_display(
        project_id: str,
        device_id: int,
        command: str,
        timeout: int | None = None,
    ) -> tuple[Any, str]:
        """Execute a display command on a device, handling common logic.

        Returns (command_result, device_name).
        """
        runtime = await _resolve_runtime_endpoint(project_id, device_id)
        endpoint = runtime.best_endpoint(preferred=preferred_transports)
        if endpoint is None:
            raise DomainError(
                code=ErrorCode.CONSOLE_UNAVAILABLE,
                message=f"No available endpoint for device {device_id}",
            )
        device_name = runtime.device_name

        target = CommandTarget(
            project_id=project_id,
            device_id=device_id,
            device_name=device_name,
        )
        requested_timeout = timeout if timeout is not None else default_command_timeout
        effective_timeout = min(requested_timeout, server_settings.max_tool_seconds, 120)
        request = CommandRequest(
            target=target,
            command=command,
            command_type=_classify_read_only_command(command),
            timeout_seconds=float(effective_timeout),
            max_output_chars=server_settings.max_output_chars,
        )

        await policy.validate_command(request)
        try:
            await transport.connect(endpoint)
            result = await transport.execute(request)
        finally:
            await transport.close()

        # Device output is untrusted and may include credentials even for a
        # nominally read-only display command. Redaction is mandatory at the
        # MCP boundary in v0.1.
        result = result.model_copy(update={"raw_output": redact_sensitive(result.raw_output)})

        return result, device_name

    @mcp.tool(
        name="h3c_list_devices",
        description=(
            "List H3C/Comware candidate devices in an HCL project. "
            "Includes stopped or unknown candidates and marks each device operable only "
            "when a verified runtime endpoint is available."
        ),
    )
    async def h3c_list_devices(project_id: ProjectId) -> ToolResult:
        """List H3C/Comware candidates and their current operability.

        Args:
            project_id: The HCL project identifier.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            topology = await project_repo.get_topology(project_id)
            runtimes = await runtime_disc.discover_project(project_id)

            runtime_map = {rt.device_id: rt for rt in runtimes}
            devices_data = []
            operable_count = 0

            for device in topology.devices:
                if not _is_comware_candidate(
                    device.model,
                    device.category,
                    device.comware_version,
                ):
                    continue
                rt = runtime_map.get(device.device_id)
                is_operable = rt is not None and rt.is_running and len(rt.endpoints) > 0
                if is_operable:
                    operable_count += 1
                devices_data.append(
                    {
                        "device_id": device.device_id,
                        "name": device.name,
                        "model": device.model,
                        "category": device.category,
                        "state": rt.state.value if rt else "unknown",
                        "operable": is_operable,
                    }
                )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "project_id": project_id,
                    "devices": devices_data,
                    "total_count": len(devices_data),
                    "operable_count": operable_count,
                },
                target={"project_id": project_id},
                duration_ms=round(duration_ms, 2),
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to list devices")

    @mcp.tool(
        name="h3c_get_facts",
        description=(
            "Get basic facts for an H3C device: system name, software version, "
            "uptime, serial number, and hardware info from 'display version'."
        ),
    )
    async def h3c_get_facts(project_id: ProjectId, device_id: DeviceId) -> ToolResult:
        """Get device facts for an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            cmd_result, device_name = await _execute_display(project_id, device_id, "display version")
            parsed = _public_parsed_data(
                parser.parse(
                    cmd_result.raw_output,
                    model="unknown",
                    version="unknown",
                    command="display version",
                )
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "facts": parsed or {},
                    "raw": cmd_result.raw_output if not parsed else None,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get device facts")

    @mcp.tool(
        name="h3c_run_display",
        description=(
            "Execute a read-only display/diagnostic command on an H3C device. "
            "Only display, ping, and tracert commands are allowed. "
            "Returns raw output and (if available) structured parsed data. "
            "Use h3c_ping or h3c_trace_route for structured ping/tracert results."
        ),
    )
    async def h3c_run_display(
        project_id: ProjectId,
        device_id: DeviceId,
        command: DisplayCommand,
        timeout: Annotated[int, Field(ge=1, le=120, description="Command timeout in seconds")] = (
            default_command_timeout
        ),
    ) -> ToolResult:
        """Execute a read-only display command on an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            command: CLI command text (display/diagnostic only).
            timeout: Command timeout in seconds (1-120).
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            cmd_result, device_name = await _execute_display(project_id, device_id, command, timeout=timeout)

            parsed_data = None
            with contextlib.suppress(DomainError):
                parsed_data = _public_parsed_data(
                    parser.parse(
                        cmd_result.raw_output,
                        model="unknown",
                        version="unknown",
                        command=command,
                    )
                )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "command": command,
                    "raw_output": cmd_result.raw_output,
                    "parsed": parsed_data,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to execute display command")

    @mcp.tool(
        name="h3c_get_config",
        description=(
            "Retrieve running or startup configuration from an H3C device. "
            "Sensitive data (passwords, keys, SNMP communities) is always redacted in v0.1. "
            "Use source='startup' for the saved configuration."
        ),
    )
    async def h3c_get_config(
        project_id: ProjectId,
        device_id: DeviceId,
        source: Literal["running", "startup"] = "running",
        redact: bool = True,
    ) -> ToolResult:
        """Retrieve device configuration.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            source: 'running' for current config, 'startup' for saved config.
            redact: Whether to redact sensitive information. Default True.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            if not redact:
                raise DomainError(
                    code=ErrorCode.POLICY_DENIED,
                    message="Unredacted configuration retrieval is disabled in v0.1",
                )

            command = (
                "display current-configuration" if source == "running" else "display saved-configuration"
            )
            cmd_result, device_name = await _execute_display(project_id, device_id, command, timeout=60)

            output = cmd_result.raw_output

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "source": source,
                    "config": output,
                    "redacted": redact,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get device configuration")

    @mcp.tool(
        name="h3c_get_interfaces",
        description=(
            "Get interface list and status for an H3C device. "
            "Returns interface name, link status, speed, and description for each interface."
        ),
    )
    async def h3c_get_interfaces(project_id: ProjectId, device_id: DeviceId) -> ToolResult:
        """Get interface list for an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            cmd_result, device_name = await _execute_display(
                project_id, device_id, "display interface brief", timeout=30
            )
            parsed = _public_parsed_data(
                parser.parse(
                    cmd_result.raw_output,
                    model="unknown",
                    version="unknown",
                    command="display interface brief",
                )
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "interfaces": (parsed or {}).get("interfaces", []),
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get interfaces")

    @mcp.tool(
        name="h3c_ping",
        description=(
            "Ping a destination from an H3C device. "
            "Returns per-packet results and summary statistics. "
            "Use this instead of h3c_run_display for structured ping results."
        ),
    )
    async def h3c_ping(
        project_id: ProjectId,
        device_id: DeviceId,
        destination: SafeDestination,
        count: Annotated[int, Field(ge=1, le=100, description="Number of ping packets")] = 5,
    ) -> ToolResult:
        """Ping a destination from an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            destination: Target IP address or hostname.
            count: Number of ping packets (1-100).
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            count = max(1, min(count, 100))
            command = f"ping -c {count} {destination}"
            cmd_result, device_name = await _execute_display(project_id, device_id, command, timeout=30)
            parsed = _public_parsed_data(
                parser.parse(
                    cmd_result.raw_output,
                    model="unknown",
                    version="unknown",
                    command="ping",
                )
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "destination": destination,
                    "count": count,
                    "result": parsed or {},
                    "raw_output": cmd_result.raw_output,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to execute ping")

    @mcp.tool(
        name="h3c_trace_route",
        description=(
            "Trace route to a destination from an H3C device. "
            "Returns per-hop results with latency. "
            "Use this instead of h3c_run_display for structured traceroute results."
        ),
    )
    async def h3c_trace_route(
        project_id: ProjectId,
        device_id: DeviceId,
        destination: SafeDestination,
        max_hops: Annotated[int, Field(ge=1, le=255, description="Maximum number of hops")] = 30,
    ) -> ToolResult:
        """Trace route to a destination from an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            destination: Target IP address or hostname.
            max_hops: Maximum number of hops (1-255).
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            max_hops = max(1, min(max_hops, 255))
            command = f"tracert -m {max_hops} {destination}"
            cmd_result, device_name = await _execute_display(project_id, device_id, command, timeout=60)
            parsed = _public_parsed_data(
                parser.parse(
                    cmd_result.raw_output,
                    model="unknown",
                    version="unknown",
                    command="tracert",
                )
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "destination": destination,
                    "max_hops": max_hops,
                    "result": parsed or {},
                    "raw_output": cmd_result.raw_output,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
                content_trust="untrusted_device_output",
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to execute trace route")

    @mcp.tool(
        name="h3c_diff_config",
        description=(
            "Compare running configuration against a candidate or startup config. "
            "In v0.1, this returns a placeholder indicating the feature is not yet "
            "fully implemented. Full diff capability will be available in v0.2."
        ),
    )
    async def h3c_diff_config(
        project_id: ProjectId,
        device_id: DeviceId,
        candidate: CandidateConfig = "",
    ) -> ToolResult:
        """Compare device configuration against a candidate config.

        In v0.1, this is a placeholder returning not-implemented.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
            candidate: Candidate configuration text to diff against (optional).
        """
        request_id = str(uuid.uuid4())
        try:
            raise DomainError(
                code=ErrorCode.NOT_IMPLEMENTED,
                message="Configuration diff is not implemented in v0.1 (planned for v0.2).",
            )
        except DomainError as e:
            return map_domain_error(e, request_id)
