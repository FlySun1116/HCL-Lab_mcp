"""Device session manager with a transport adapter for MCP tools.

ConsoleTelnetTransport uses session-per-device (bind at construction).
MCP tools use request-per-request (connect → execute → close per call).

SessionManagerTransport bridges these: it holds a DeviceSessionManager and
routes connect/execute/close to the right per-device session underneath.
"""

from __future__ import annotations

import contextlib
import logging

from h3c_hcl_mcp.adapters.comware.console_telnet import ConsoleTelnetTransport
from h3c_hcl_mcp.adapters.comware.session import DeviceSession
from h3c_hcl_mcp.domain.command import CommandRequest, CommandResult
from h3c_hcl_mcp.domain.device import RuntimeEndpoint
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.device_transport import DeviceTransport

logger = logging.getLogger(__name__)

_DEVICE_KEY = tuple[str, int]  # (project_id, device_id)


class DeviceSessionManager:
    """Manages a pool of device sessions and underlying telnet transports.

    Sessions are reused across requests to the same device.
    Each device gets an exclusive session lock.
    """

    def __init__(self) -> None:
        self._sessions: dict[_DEVICE_KEY, DeviceSession] = {}
        self._transports: dict[_DEVICE_KEY, ConsoleTelnetTransport] = {}

    def get_or_create_session(
        self, project_id: str, device_id: int, device_name: str = ""
    ) -> DeviceSession:
        """Get an existing session or create a new one."""
        key = (project_id, device_id)
        if key not in self._sessions:
            self._sessions[key] = DeviceSession(
                device_id=device_id,
                device_name=device_name or f"device-{device_id}",
            )
        return self._sessions[key]

    def get_or_create_transport(
        self, project_id: str, device_id: int
    ) -> ConsoleTelnetTransport:
        """Get or create the underlying ConsoleTelnetTransport for a device."""
        key = (project_id, device_id)
        if key not in self._transports:
            session = self.get_or_create_session(project_id, device_id)
            self._transports[key] = ConsoleTelnetTransport(session)
        return self._transports[key]

    async def close_device(self, project_id: str, device_id: int) -> None:
        """Close and remove the session for a device."""
        key = (project_id, device_id)
        transport = self._transports.pop(key, None)
        if transport is not None:
            try:
                await transport.close()
            except Exception:
                logger.warning(
                    "Error closing transport for device %s/%s",
                    project_id, device_id, exc_info=True,
                )
        self._sessions.pop(key, None)

    async def close_all(self) -> None:
        """Close all sessions and transports."""
        for transport in list(self._transports.values()):
            with contextlib.suppress(Exception):
                await transport.close()
        self._transports.clear()
        self._sessions.clear()

    @property
    def active_sessions(self) -> int:
        """Number of sessions with active connections."""
        return sum(1 for s in self._sessions.values() if s.is_connected)


class SessionManagerTransport(DeviceTransport):
    """DeviceTransport that routes to per-device sessions via DeviceSessionManager.

    This implements the connect/execute/close pattern expected by MCP tools
    while reusing persistent per-device sessions underneath.

    Usage pattern in tools:
        await transport.connect(endpoint)    # opens/reuses device session
        result = await transport.execute(req) # runs on that device
        await transport.close()             # soft-release (session stays alive)
    """

    def __init__(self, manager: DeviceSessionManager) -> None:
        self._manager = manager
        self._current_key: _DEVICE_KEY | None = None
        self._current_transport: ConsoleTelnetTransport | None = None

    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        """Connect to a device via the given endpoint.

        Extracts project_id and device_id from endpoint.extra.
        Creates or reuses a persistent session for this device.
        """
        project_id = endpoint.extra.get("project_id", "")
        device_id_str = endpoint.extra.get("device_id", "")
        if not project_id or not device_id_str:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Endpoint must include project_id and device_id in extra",
                {"extra": endpoint.extra},
            )
        device_id = int(device_id_str)

        self._current_key = (project_id, device_id)
        self._current_transport = self._manager.get_or_create_transport(
            project_id, device_id
        )

        session = self._manager.get_or_create_session(project_id, device_id)
        if not session.is_connected:
            await self._current_transport.connect(endpoint)

    async def execute(self, request: CommandRequest) -> CommandResult:
        """Execute a command on the currently connected device."""
        if self._current_transport is None:
            raise DomainError(
                ErrorCode.CONNECTION_CLOSED,
                "Not connected. Call connect() first.",
            )
        return await self._current_transport.execute(request)

    async def execute_config(
        self, commands: list[str], timeout_seconds: float = 30.0
    ) -> CommandResult:
        """Configuration writes are disabled in v0.1."""
        if self._current_transport is None:
            raise DomainError(
                ErrorCode.CONNECTION_CLOSED,
                "Not connected.",
            )
        return await self._current_transport.execute_config(commands, timeout_seconds)

    async def close(self) -> None:
        """Soft-release: clears the current transport reference.

        The underlying session stays alive for reuse.
        Use close_permanent() to fully tear down the session.
        """
        self._current_transport = None
        self._current_key = None

    async def close_permanent(self) -> None:
        """Permanently close the current device session."""
        if self._current_key is not None:
            await self._manager.close_device(*self._current_key)
        self._current_transport = None
        self._current_key = None
