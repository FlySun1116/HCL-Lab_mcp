"""NETCONF transport placeholder — returns NOT_IMPLEMENTED.

NETCONF transport will be implemented in v0.3.0.
"""

from __future__ import annotations

from h3c_hcl_mcp.domain.command import CommandRequest, CommandResult
from h3c_hcl_mcp.domain.device import RuntimeEndpoint
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.device_transport import DeviceTransport


class NetconfTransport(DeviceTransport):
    """NETCONF transport placeholder — not implemented in v0.1."""

    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        raise DomainError(
            ErrorCode.NOT_IMPLEMENTED,
            "NETCONF transport is planned for v0.3.0",
            {"transport": "netconf"},
        )

    async def execute(self, request: CommandRequest) -> CommandResult:
        raise DomainError(
            ErrorCode.NOT_IMPLEMENTED,
            "NETCONF transport is planned for v0.3.0",
            {"transport": "netconf"},
        )

    async def execute_config(self, commands: list[str], timeout_seconds: float = 30.0) -> CommandResult:
        raise DomainError(
            ErrorCode.NOT_IMPLEMENTED,
            "NETCONF transport is planned for v0.3.0",
            {"transport": "netconf"},
        )

    async def close(self) -> None:
        pass
