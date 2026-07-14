"""Command validation — allow/deny rules with injection detection.

All commands are validated against strict allowlists before execution.
v0.1 is read-only: only display and diagnostic commands are allowed.
"""

from __future__ import annotations

import re
from re import Pattern

from h3c_hcl_mcp.domain.command import CommandType

# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

ALLOWED_DISPLAY_COMMANDS: list[str] = [
    "display version",
    "display device",
    "display current-configuration",
    "display saved-configuration",
    "display interface",
    "display interface brief",
    "display ip interface",
    "display ip routing-table",
    "display lldp neighbor-information",
    "display lldp neighbor-information list",
    "display mac-address",
    "display arp",
    "display vlan",
    "display cpu-usage",
    "display memory",
    "display logbuffer",
    "display clock",
    "display users",
    "display diagnostic-information",
]

ALLOWED_DIAGNOSTIC_COMMANDS: list[str] = [
    "ping",
    "tracert",
]

# ---------------------------------------------------------------------------
# Denied patterns (injection, dangerous operations)
# ---------------------------------------------------------------------------

# Commands containing these substrings are ALWAYS rejected
DENIED_SUBSTRINGS: list[str] = [
    "reboot",
    "reset",
    "format",
    "delete",
    "erase",
    "copy",
    "tftp",
    "ftp",
    "save",
    "startup",
    "undo",
    "import",
    "export",
    "install",
    "upgrade",
    "tar",
    "unzip",
    "mkdir",
    "rmdir",
    "move",
    "rename",
    "more",
    "system-view",
]

# Regex patterns that indicate injection or abuse
INJECTION_PATTERNS: list[tuple[Pattern[str], str]] = [
    # Control characters below 0x20 except space (0x20) and tab (0x09)
    (re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"), "control character detected"),
    # Newlines
    (re.compile(r"[\n\r]"), "newline character in command"),
    # Command separators
    (re.compile(r";"), "command separator ';' not allowed"),
    # Pipe (output filtering — blocked for defense-in-depth)
    (re.compile(r"\|"), "pipe character not allowed"),
    # I/O redirection
    (re.compile(r"[<>]"), "I/O redirection not allowed"),
    # Shell escapes / variable expansion
    (re.compile(r"[!$]"), "shell escape not allowed"),
    # Backticks (command substitution)
    (re.compile(r"`"), "backtick command substitution not allowed"),
    # SQL injection patterns (defense-in-depth)
    (
        re.compile(
            r"(?i)(\bselect\b.*\bfrom\b|\binsert\b.*\binto\b|\bdelete\b.*\bfrom\b|\bupdate\b.*\bset\b|\bdrop\b.*\btable\b|\bunion\b.*\bselect\b|\bexec\b|\bexecute\b)"
        ),
        "SQL injection pattern detected",
    ),
    # URL/URI schemes (exfiltration attempts)
    (
        re.compile(r"(?i)(url\s*=|\bhttps?://|\bftp://|\bdata:\s*text|\bjavascript:)"),
        "URL injection pattern detected",
    ),
]


def _command_matches_prefix(command: str, prefixes: list[str]) -> bool:
    """Check if `command` starts with one of the allowed prefixes."""
    lowered = command.strip().lower()
    return any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in prefixes)


# Pre-compiled regex patterns for denied substrings (word-boundary matching)
_DENIED_REGEX: Pattern[str] = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in DENIED_SUBSTRINGS) + r")\b",
    re.IGNORECASE,
)


def _check_denied_substrings(command: str) -> str | None:
    """Check for dangerous keywords anywhere in the command.

    Uses word-boundary matching to avoid false positives
    (e.g., 'format' matching inside 'information').

    Returns rejection reason if found, None otherwise.
    """
    match = _DENIED_REGEX.search(command)
    if match:
        return f"denied pattern in command: '{match.group()}'"
    return None


def _check_injection_patterns(command: str) -> str | None:
    """Check for injection/attack patterns.

    Returns rejection reason if found, None otherwise.
    """
    for pattern, reason in INJECTION_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def validate_command(command: str, command_type: CommandType) -> tuple[bool, str | None]:
    """Validate a command against the security policy.

    Checks:
    1. Injection patterns (control chars, separators, escapes, SQL)
    2. Denied dangerous substrings
    3. Command matches allowlist for its type

    Args:
        command: Raw command string from the request.
        command_type: Classification of the command.

    Returns:
        (is_valid, rejection_reason_if_invalid) tuple.
        rejection_reason is None when the command is valid.
    """
    if not command or not command.strip():
        return False, "empty command"

    # Step 1: injection patterns (highest priority)
    injection_reason = _check_injection_patterns(command)
    if injection_reason:
        return False, injection_reason

    # Step 2: denied substrings
    denied_reason = _check_denied_substrings(command)
    if denied_reason:
        return False, denied_reason

    # Step 3: allowlist check by command type
    if command_type == CommandType.DISPLAY:
        if not _command_matches_prefix(command, ALLOWED_DISPLAY_COMMANDS):
            return False, f"command not in display allowlist: '{command}'"

    elif command_type == CommandType.DIAGNOSTIC:
        if not _command_matches_prefix(command, ALLOWED_DIAGNOSTIC_COMMANDS):
            return False, f"command not in diagnostic allowlist: '{command}'"

    elif command_type in (CommandType.CONFIG, CommandType.SAVE, CommandType.RESET):
        return False, f"command type '{command_type.value}' is not allowed in current mode"

    else:
        return False, f"unknown command type: '{command_type.value}'"

    # Step 4: additional ping/tracert validation — only allow safe arguments
    if command_type == CommandType.DIAGNOSTIC:
        diagnostic_reason = _validate_diagnostic_args(command)
        if diagnostic_reason:
            return False, diagnostic_reason

    return True, None


def _validate_diagnostic_args(command: str) -> str | None:
    """Additional validation for ping/tracert arguments.

    Reject attempts to inject via ping/tracert options.
    """
    lowered = command.lower().strip()

    # Check for common ping attack payloads
    ping_injection_patterns: list[tuple[Pattern[str], str]] = [
        (re.compile(r"(?i)\bping\b.*[;&|`$<>]"), "ping with injection characters"),
        (re.compile(r"(?i)\bping\b.*-c\s*0"), "ping with suspicious count"),
        (
            re.compile(r"(?i)\bping\b.*\b(reboot|reset|format|delete|exec|cmd|sh\b|bash\b)"),
            "ping with dangerous keywords",
        ),
        (re.compile(r"(?i)\btracert\b.*[;&|`$<>]"), "tracert with injection characters"),
        (
            re.compile(r"(?i)\btracert\b.*\b(reboot|reset|format|delete|exec|cmd|sh\b|bash\b)"),
            "tracert with dangerous keywords",
        ),
    ]

    for pattern, reason in ping_injection_patterns:
        if pattern.search(lowered):
            return reason

    return None
