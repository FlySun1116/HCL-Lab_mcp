"""Port: DeviceTransport — connect and execute commands on network devices."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3c_hcl_mcp.domain.command import CommandRequest, CommandResult
from h3c_hcl_mcp.domain.device import RuntimeEndpoint


class DeviceTransport(ABC):
    """Abstract transport for executing commands on a network device.

    Implementations: ConsoleTelnetTransport, SshTransport, NetconfTransport.
    Each transport instance is bound to a single device session.
    """

    @abstractmethod
    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        """Establish a connection to the device.

        Args:
            endpoint: The discovered runtime endpoint to connect to.

        Raises:
            DomainError(CONNECTION_FAILED): could not establish connection.
            DomainError(PROMPT_TIMEOUT): connected but no CLI prompt received.
        """
        ...

    @abstractmethod
    async def execute(self, request: CommandRequest) -> CommandResult:
        """Execute a single command and return the result.

        The implementation must handle:
        - Startup noise filtering
        - Echo suppression
        - Pagination (---- More ----)
        - Prompt detection and normalization
        - Timeout enforcement
        - Output truncation

        Raises:
            DomainError(COMMAND_DENIED): policy rejected this command.
            DomainError(COMMAND_TIMEOUT): command did not complete in time.
            DomainError(CONNECTION_CLOSED): session was lost.
        """
        ...

    @abstractmethod
    async def execute_config(self, commands: list[str], timeout_seconds: float = 30.0) -> CommandResult:
        """Execute a sequence of configuration commands.

        The implementation should enter config mode, execute commands, and exit.
        This is designed for the future write path (v0.2+).

        Raises:
            DomainError(WRITE_DISABLED): write operations are not enabled.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully close the session and free resources."""
        ...
