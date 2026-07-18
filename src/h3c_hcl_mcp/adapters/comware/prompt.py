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

# A CLI prompt is framing, not merely text that resembles a prompt.  Only the
# final, otherwise-empty line in the current receive buffer may terminate a
# response.  This prevents command output such as ``status: <failed>`` from
# being mistaken for the device prompt.
_FINAL_CLI_PROMPT_RE = re.compile(r"(?:^|[\r\n])[ \t]*(<[^>\r\n]+>|\[[^\]\r\n]+\])[ \t]*(?:\r?\n)?\Z")

# Comware may append a Ctrl+C hint to the pagination marker.  The marker must
# still start the final independent line.
_FINAL_MORE_PROMPT_RE = re.compile(
    r"(?:^|[\r\n])[ \t]*(----\s*More\s*----)[^\r\n]*(?:\r?\n)?\Z",
    re.IGNORECASE,
)


def detect_prompt(buffer: str, expected_prompt: str | None = None) -> str | None:
    """Extract a terminal CLI prompt from a buffer.

    A match must occupy the final independent line.  When ``expected_prompt``
    is supplied, a CLI prompt must exactly match the prompt captured for this
    read-only session.  The v0.1 command set never changes CLI view, so a mode
    transition is ambiguous device output and must fail closed.  Pagination
    prompts are accepted independently of the expected CLI prompt.

    Args:
        buffer: Raw text received from the device console.
        expected_prompt: Previously captured prompt for this session.

    Returns:
        The prompt string (e.g. '<H3C>', '[H3C-GigabitEthernet1/0/1]'), or None.
    """
    more_match = _FINAL_MORE_PROMPT_RE.search(buffer)
    if more_match is not None:
        return more_match.group(1)

    match = _FINAL_CLI_PROMPT_RE.search(buffer)
    if match is None:
        return None
    prompt = match.group(1)
    if expected_prompt is not None and not _matches_expected_prompt(prompt, expected_prompt):
        return None
    return prompt


def _find_last_prompt_match(buffer: str) -> re.Match[str] | None:
    """Return the terminal CLI-prompt match object for compatibility."""
    return _FINAL_CLI_PROMPT_RE.search(buffer)


def _matches_expected_prompt(prompt: str, expected_prompt: str) -> bool:
    """Require stable framing for v0.1's non-mode-changing commands."""
    return prompt == expected_prompt


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
