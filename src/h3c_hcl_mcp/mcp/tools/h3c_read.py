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
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.error_mapping import internal_error, map_domain_error
from h3c_hcl_mcp.ports.command_parser import CommandParser
from h3c_hcl_mcp.ports.device_transport import DeviceTransport
from h3c_hcl_mcp.ports.policy_engine import PolicyEngine
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery
from h3c_hcl_mcp.ports.secret_provider import SecretProvider


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
    _secrets: SecretProvider = deps["secret_provider"]  # reserved for future use

    async def _get_device_name(project_id: str, device_id: int) -> str:
        """Resolve a device name from the project topology."""
        try:
            topology = await project_repo.get_topology(project_id)
            device = topology.get_device(device_id)
            if device:
                return device.name
        except DomainError:
            pass
        return f"device_{device_id}"

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
        timeout: int = 20,
    ) -> tuple[Any, str]:
        """Execute a display command on a device, handling common logic.

        Returns (command_result, device_name).
        """
        runtime = await _resolve_runtime_endpoint(project_id, device_id)
        endpoint = runtime.best_endpoint()
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
        request = CommandRequest(
            target=target,
            command=command,
            command_type=CommandType.DISPLAY,
            timeout_seconds=float(timeout),
        )

        await policy.validate_command(request)
        await transport.connect(endpoint)
        try:
            result = await transport.execute(request)
        finally:
            await transport.close()

        return result, device_name

    @mcp.tool(
        name="h3c_list_devices",
        description=(
            "List operable H3C devices in an HCL project. "
            "Returns devices that are running and have available console/SSH endpoints."
        ),
    )
    async def h3c_list_devices(project_id: str) -> ToolResult:
        """List operable H3C devices in a project.

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
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to list devices")

    @mcp.tool(
        name="h3c_get_facts",
        description=(
            "Get basic facts for an H3C device: system name, software version, "
            "uptime, serial number, and hardware info. Uses 'display version' and "
            "'display device' commands."
        ),
    )
    async def h3c_get_facts(project_id: str, device_id: int) -> ToolResult:
        """Get device facts for an H3C device.

        Args:
            project_id: The HCL project identifier.
            device_id: Numeric device ID within the project.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()

        try:
            cmd_result, device_name = await _execute_display(
                project_id, device_id, "display version", timeout=20
            )
            parsed = parser.parse(
                cmd_result.raw_output,
                model="unknown",
                version="unknown",
                command="display version",
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "facts": parsed,
                    "raw": cmd_result.raw_output if not parsed else None,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
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
        project_id: str,
        device_id: int,
        command: str,
        timeout: Annotated[int, Field(ge=1, le=120, description="Command timeout in seconds")] = 20,
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
                parsed_data = parser.parse(
                    cmd_result.raw_output,
                    model="unknown",
                    version="unknown",
                    command=command,
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
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to execute display command")

    @mcp.tool(
        name="h3c_get_config",
        description=(
            "Retrieve running or startup configuration from an H3C device. "
            "Sensitive data (passwords, keys, SNMP communities) is redacted by default. "
            "Use source='startup' for the saved configuration. "
            "Use redact=False to disable automatic redaction (requires justification)."
        ),
    )
    async def h3c_get_config(
        project_id: str,
        device_id: int,
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
            if source not in ("running", "startup"):
                raise DomainError(
                    code=ErrorCode.INVALID_ARGUMENT,
                    message=f"Invalid config source: {source}. Use 'running' or 'startup'.",
                )

            command = (
                "display current-configuration" if source == "running" else "display saved-configuration"
            )
            cmd_result, device_name = await _execute_display(project_id, device_id, command, timeout=60)

            output = cmd_result.raw_output
            if redact:
                # Basic redaction patterns
                import re

                redactions = [
                    (r"(password\s+)\S+", r"\1***"),
                    (r"(cipher\s+)\S+", r"\1***"),
                    (r"(simple\s+)\S+", r"\1***"),
                    (r"(snmp-agent community\s+)\S+", r"\1***"),
                    (r"(pre-shared-key\s+)\S+", r"\1***"),
                ]
                for pattern, replacement in redactions:
                    output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)

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
            )

        except DomainError as e:
            return map_domain_error(e, request_id)
        except Exception:
            return internal_error(request_id, "Failed to get device configuration")

    @mcp.tool(
        name="h3c_get_interfaces",
        description=(
            "Get interface list and status for an H3C device. "
            "Returns interface name, admin status, operational status, "
            "speed, duplex, and description for each interface."
        ),
    )
    async def h3c_get_interfaces(project_id: str, device_id: int) -> ToolResult:
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
            parsed = parser.parse(
                cmd_result.raw_output,
                model="unknown",
                version="unknown",
                command="display interface brief",
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "interfaces": parsed.get("interfaces", parsed),
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
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
        project_id: str,
        device_id: int,
        destination: str,
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
            parsed = parser.parse(
                cmd_result.raw_output,
                model="unknown",
                version="unknown",
                command="ping",
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "destination": destination,
                    "count": count,
                    "result": parsed,
                    "raw_output": cmd_result.raw_output if not parsed else None,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
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
        project_id: str,
        device_id: int,
        destination: str,
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
            parsed = parser.parse(
                cmd_result.raw_output,
                model="unknown",
                version="unknown",
                command="tracert",
            )

            duration_ms = (time.monotonic() - start) * 1000
            return ToolResult.success(
                request_id=request_id,
                data={
                    "device_id": device_id,
                    "device_name": device_name,
                    "destination": destination,
                    "max_hops": max_hops,
                    "result": parsed,
                    "raw_output": cmd_result.raw_output if not parsed else None,
                },
                target={"project_id": project_id, "device_id": device_id},
                warnings=cmd_result.warnings,
                duration_ms=round(duration_ms, 2),
                truncated=cmd_result.truncated,
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
        project_id: str,
        device_id: int,
        candidate: str = "",
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
