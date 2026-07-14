"""Role definitions and permission matrix for MCP tools.

Roles follow principle of least privilege — by default, every role
has the minimal set of permissions needed.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Predefined roles for tool authorization."""

    ANONYMOUS = "anonymous"  # No authentication provided
    VIEWER = "viewer"  # Read-only access to projects, devices, facts
    OPERATOR = "operator"  # Can run diagnostic commands (ping, tracert)
    ADMIN = "admin"  # Can approve change plans
    LAB_ADMIN = "lab_admin"  # Full access including configuration writes


# ---------------------------------------------------------------------------
# Tool -> minimum role required
# ---------------------------------------------------------------------------
TOOL_PERMISSIONS: dict[str, Role] = {
    # Project discovery
    "list_projects": Role.VIEWER,
    "get_project": Role.VIEWER,
    # Device discovery
    "list_devices": Role.VIEWER,
    "get_device": Role.VIEWER,
    # Console availability
    "check_console": Role.VIEWER,
    "get_console_info": Role.VIEWER,
    # Read-only commands
    "get_device_facts": Role.VIEWER,
    "get_interfaces": Role.VIEWER,
    "get_config": Role.VIEWER,
    "execute_display": Role.VIEWER,
    # Diagnostic commands
    "execute_diagnostic": Role.OPERATOR,
    # Write operations (disabled in v0.1 default policy)
    "plan_change": Role.ADMIN,
    "approve_change": Role.ADMIN,
    "apply_change": Role.ADMIN,
    "verify_change": Role.ADMIN,
    "rollback_change": Role.ADMIN,
    # Audit
    "query_audit": Role.ADMIN,
    # Admin
    "health_check": Role.VIEWER,
    "list_sessions": Role.ADMIN,
}


def get_required_role(tool_name: str) -> Role:
    """Return the minimum role required to access a tool.

    Unknown tools default to LAB_ADMIN (deny by default).
    """
    return TOOL_PERMISSIONS.get(tool_name, Role.LAB_ADMIN)


def check_permission(tool_name: str, caller_role: Role) -> bool:
    """Check if a caller with `caller_role` can access `tool_name`.

    Role hierarchy: anonymous < viewer < operator < admin < lab_admin
    """
    required = get_required_role(tool_name)
    role_order = list(Role)
    return role_order.index(caller_role) >= role_order.index(required)
