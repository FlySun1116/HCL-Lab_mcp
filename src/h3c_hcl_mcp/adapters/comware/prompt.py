"""Comware CLI prompt state machine.

Detects and normalises Comware CLI prompt modes including:
- User view: <sysname>
- System view: [sysname]
- Interface/sub views: [sysname-Interface-...]
- Pagination (More): ---- More ----
- Login/Password prompts
"""

from __future__ import annotations

import re

# ---- Prompt patterns ----

# User view: <H3C>, <Switch>, <Router-1>
_USER_VIEW_RE = re.compile(r"<([^>]+)>")

# System view and all sub-views: [H3C], [H3C-GigabitEthernet1/0/1], [H3C-route-policy]
_SYSTEM_VIEW_RE = re.compile(r"\[([^\]]+)\]")

# Pagination prompt: ---- More ---- (possibly with Ctrl+C hint on next line)
_MORE_RE = re.compile(r"----\s*More\s*----", re.IGNORECASE)

# Login prompt variations
_LOGIN_RE = re.compile(r"(?:login|Username)\s*:\s*$", re.IGNORECASE | re.MULTILINE)

# Password prompt
_PASSWORD_RE = re.compile(r"Password\s*:\s*$", re.IGNORECASE | re.MULTILINE)

# Any valid prompt pattern (user view, system view, or more)
_ANY_PROMPT = re.compile(
    r"<[^>\r\n]+>|\[[^\]\r\n]+\]|----\s*More\s*----",
    re.IGNORECASE,
)


def detect_prompt(buffer: str) -> str | None:
    """Extract the last CLI prompt from a buffer.

    Scans the buffer for the last occurrence of a known prompt pattern.
    Returns the matched prompt string, or None if no prompt is found.

    Args:
        buffer: Raw text received from the device console.

    Returns:
        The prompt string (e.g. '<H3C>', '[H3C-GigabitEthernet1/0/1]'), or None.
    """
    matches = list(_ANY_PROMPT.finditer(buffer))
    if not matches:
        return None
    return matches[-1].group(0)


def _find_last_prompt_match(buffer: str) -> re.Match | None:
    """Return the last regex match object for a prompt in the buffer."""
    matches = list(_ANY_PROMPT.finditer(buffer))
    return matches[-1] if matches else None


def normalize_prompt(prompt: str) -> str:
    """Normalize a detected prompt string.

    Strips trailing whitespace and ensures consistent formatting.
    The prompt itself is preserved (sysname is not stripped).

    Args:
        prompt: Raw prompt string from detect_prompt.

    Returns:
        Normalized prompt string.
    """
    return prompt.strip()


def is_more_prompt(buffer: str) -> bool:
    """Check whether the buffer ends with a pagination (---- More ----) prompt.

    Comware uses '---- More ----' to indicate output pagination.
    The client should send a space character to continue.

    Args:
        buffer: Raw text received from the device console.

    Returns:
        True if the last prompt in the buffer is a More prompt.
    """
    prompt = detect_prompt(buffer)
    if prompt is None:
        return False
    return bool(_MORE_RE.match(prompt))


def is_login_prompt(buffer: str) -> bool:
    """Check whether the buffer contains a login or password prompt.

    Args:
        buffer: Raw text received from the device console.

    Returns:
        True if the buffer indicates login or password entry is expected.
    """
    return bool(_LOGIN_RE.search(buffer) or _PASSWORD_RE.search(buffer))


def is_user_view(buffer: str) -> bool:
    """Check whether the device is in user view (angle-bracket prompt).

    Args:
        buffer: Raw text received from the device console.

    Returns:
        True if the last prompt is a user-view prompt.
    """
    prompt = detect_prompt(buffer)
    if prompt is None:
        return False
    return prompt.startswith("<") and prompt.endswith(">")


def is_system_view(buffer: str) -> bool:
    """Check whether the device is in system or sub-view (square-bracket prompt).

    Args:
        buffer: Raw text received from the device console.

    Returns:
        True if the last prompt is a system-view prompt.
    """
    prompt = detect_prompt(buffer)
    if prompt is None:
        return False
    return prompt.startswith("[") and prompt.endswith("]")


def extract_sysname(buffer: str) -> str | None:
    """Extract the device sysname from the last prompt.

    Args:
        buffer: Raw text received from the device console.

    Returns:
        The sysname (e.g. 'H3C'), or None if no prompt is found.
    """
    prompt = detect_prompt(buffer)
    if prompt is None:
        return None

    # User view: <sysname>
    m = _USER_VIEW_RE.match(prompt)
    if m:
        return m.group(1)

    # System view: [sysname] or [sysname-...]
    m = _SYSTEM_VIEW_RE.match(prompt)
    if m:
        full = m.group(1)
        # Strip sub-view suffix (e.g. '-GigabitEthernet1/0/1')
        dash_idx = full.find("-")
        return full if dash_idx == -1 else full[:dash_idx]

    return None
