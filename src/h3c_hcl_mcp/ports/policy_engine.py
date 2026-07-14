"""Port: PolicyEngine — authorize tool calls and validate commands."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3c_hcl_mcp.domain.command import CommandRequest


class PolicyEngine(ABC):
    """Central policy decision point for all tool invocations.

    Checks tool access, command allow/deny lists, and risk levels.
    Server-side enforcement — does not rely on MCP client UI.
    """

    @abstractmethod
    async def authorize(self, tool_name: str, caller: str = "unknown") -> bool:
        """Check whether the caller is authorized to use a tool.

        Returns True if authorized. May log denied attempts for audit.
        """
        ...

    @abstractmethod
    async def validate_command(self, request: CommandRequest) -> bool:
        """Validate a command against the allow/deny policy.

        Checks:
        - Command prefix whitelist (display, ping, tracert for v0.1)
        - No shell injection (newlines, semicolons, pipes, redirects)
        - No control characters
        - No denied patterns (reboot, reset, format, delete)

        Returns True if the command is allowed.

        Raises:
            DomainError(COMMAND_NOT_ALLOWED): command rejected by policy.
        """
        ...

    @abstractmethod
    async def validate_change(
        self,
        target_project: str,
        target_device: int,
        commands: list[str],
    ) -> str:
        """Validate a proposed configuration change.

        Returns a risk level: 'low', 'medium', 'high'.

        Raises:
            DomainError(WRITE_DISABLED): write mode is not enabled.
        """
        ...

    @abstractmethod
    def is_write_enabled(self) -> bool:
        """Return whether write operations are globally enabled."""
        ...
