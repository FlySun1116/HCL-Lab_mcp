"""PolicyEngine implementation — central policy decision point.

Checks tool authorization, command validation, and risk levels.
All policy decisions are logged for audit trail.
"""

from __future__ import annotations

import logging

from h3c_hcl_mcp.domain.command import CommandRequest
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.policy.command_rules import validate_command
from h3c_hcl_mcp.infrastructure.policy.roles import Role, check_permission
from h3c_hcl_mcp.infrastructure.settings import PolicySettings
from h3c_hcl_mcp.ports.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)


class PolicyEngineImpl(PolicyEngine):
    """Default policy engine implementation.

    Enforces:
    - Tool authorization by role
    - Command allow/deny rules
    - Risk level assessment for changes
    - Global read-only / write enforcement
    """

    def __init__(self, settings: PolicySettings, role_mapping: dict[str, Role] | None = None) -> None:
        self._settings = settings
        # Caller -> Role mapping (default: everyone is VIEWER)
        self._roles: dict[str, Role] = role_mapping or {}
        self._default_role = Role.VIEWER

    def set_role(self, caller: str, role: Role) -> None:
        """Assign a role to a caller."""
        self._roles[caller] = role

    def get_role(self, caller: str) -> Role:
        """Get the effective role for a caller."""
        return self._roles.get(caller, self._default_role)

    # ------------------------------------------------------------------
    # PolicyEngine ABC implementation
    # ------------------------------------------------------------------

    async def authorize(self, tool_name: str, caller: str = "unknown") -> bool:
        """Check whether the caller is authorized to use a tool.

        If globally write-disabled, all write tools are denied regardless of role.
        """
        role = self.get_role(caller)

        # Global write lock
        if not self.is_write_enabled():
            write_tools = {
                "plan_change",
                "approve_change",
                "apply_change",
                "verify_change",
                "rollback_change",
            }
            if tool_name in write_tools:
                logger.info(
                    "TOOL_DENIED tool=%s caller=%s reason=write_disabled",
                    tool_name,
                    caller,
                )
                return False

        authorized = check_permission(tool_name, role)
        if not authorized:
            logger.info(
                "TOOL_DENIED tool=%s caller=%s role=%s reason=insufficient_permissions",
                tool_name,
                caller,
                role.value,
            )
        return authorized

    async def validate_command(self, request: CommandRequest) -> bool:
        """Validate a command against the allow/deny policy.

        Returns True if allowed.

        Raises:
            DomainError(COMMAND_NOT_ALLOWED): command rejected by policy.
        """
        is_valid, reason = validate_command(
            request.command,
            request.command_type,
            allowed_display_prefixes=self._settings.allow_display_prefixes,
            denied_patterns=self._settings.deny_patterns,
        )
        if not is_valid:
            raise DomainError(
                ErrorCode.COMMAND_NOT_ALLOWED,
                reason or "command rejected by policy",
                details={
                    "command": request.command,
                    "command_type": request.command_type.value,
                },
            )
        return True

    async def validate_change(
        self,
        target_project: str,
        target_device: int,
        commands: list[str],
    ) -> str:
        """Assess risk level for a proposed configuration change.

        Risk levels:
        - R0: No risk (pure display/diagnostic)
        - R1: Low risk (single config line with no service disruption)
        - R2: Medium risk (config changes that may affect traffic)
        - R3: High risk (reboot, save, delete, format)

        Returns one of: 'R0', 'R1', 'R2', 'R3'
        """
        if not self.is_write_enabled():
            raise DomainError(
                ErrorCode.WRITE_DISABLED,
                "write operations are globally disabled",
            )

        risk_score = 0
        combined = " ".join(commands).lower()

        # R3 indicators
        r3_patterns = ["reboot", "reset", "format", "delete", "erase", "save "]
        if any(p in combined for p in r3_patterns):
            return "R3"

        # R2 indicators
        r2_patterns = [
            "interface ",
            "ospf",
            "bgp",
            "vlan",
            "stp",
            "lacp",
            "aaa",
            "radius",
            "tacacs",
            "ssh server",
            "telnet server",
            "firewall",
            "acl ",
            "qos",
        ]
        if any(p in combined for p in r2_patterns):
            risk_score += 2

        # R1 indicators
        r1_patterns = ["description", "hostname", "banner", "ntp ", "syslog", "snmp "]
        if any(p in combined for p in r1_patterns):
            risk_score = max(risk_score, 1)

        if risk_score >= 3:
            return "R3"
        elif risk_score >= 2:
            return "R2"
        elif risk_score >= 1:
            return "R1"
        else:
            return "R0"

    def is_write_enabled(self) -> bool:
        """Return whether write operations are globally enabled.

        In read_only mode, all write operations are denied.
        In controlled_write, writes require approval.
        In lab_admin, writes are allowed without approval.
        """
        return self._settings.mode != "read_only"

    @property
    def mode(self) -> str:
        """Current policy mode."""
        return self._settings.mode
