"""Sensitive data redaction for device output.

All device output is considered untrusted and is sanitized before
being returned to MCP clients or stored in audit logs.
"""

from __future__ import annotations

import re
from re import Pattern

# ---------------------------------------------------------------------------
# Redaction patterns — ordered from most specific to least specific
# to avoid partial matches causing missed redactions.
# ---------------------------------------------------------------------------
_SNMP_COMMUNITY_LINE = re.compile(
    r"(?im)^[ \t]*snmp-agent[ \t]+community\b[^\r\n]*$",
)
_SNMP_USM_USER_LINE = re.compile(
    r"(?im)^[ \t]*snmp-agent[ \t]+usm-user\b[^\r\n]*$",
)
_NTP_AUTHENTICATION_LINE = re.compile(
    r"(?im)^[ \t]*ntp-service[ \t]+authentication-keyid\b[^\r\n]*$",
)
_AAA_KEY_LINE = re.compile(
    r"(?im)^[^\r\n]*\bkey[ \t]+(?:authentication|accounting)\b[^\r\n]*$",
)
_SUPER_PASSWORD_LINE = re.compile(
    r"(?im)^[ \t]*super[ \t]+password\b[^\r\n]*$",
)
_KEY_STRING_LINE = re.compile(
    r"(?im)^[ \t]*key-string\b[^\r\n]*$",
)
_WEP_KEY_LINE = re.compile(
    r"(?im)^[ \t]*wep[ \t]+key\b[^\r\n]*$",
)
_PRESHARED_KEY_LINE = re.compile(
    r"(?im)^[ \t]*(?:pre-shared-key|preshared-key)\b[^\r\n]*$",
)


REDACT_PATTERNS: list[tuple[Pattern[str], str]] = [
    # Private keys must run before generic ``key`` rules, otherwise a secret
    # line ending in "key" can consume and corrupt the PEM END marker.
    (
        re.compile(
            r"-----BEGIN[ \t]+(?:[A-Z0-9]+[ \t]+)*PRIVATE[ \t]+KEY-----"
            r".*?(?:-----END[ \t]+(?:[A-Z0-9]+[ \t]+)*PRIVATE[ \t]+KEY-----|\Z)",
            re.DOTALL | re.IGNORECASE,
        ),
        "*** PRIVATE MATERIAL REDACTED ***",
    ),
    # Comware credential-bearing syntax families are redacted as complete
    # lines. Qualifiers such as ``cipher`` and ``simple`` are metadata, not
    # the secret itself; token-oriented rules can otherwise consume only the
    # qualifier and leave the real credential visible.
    (_SNMP_COMMUNITY_LINE, "snmp-agent community *** REDACTED ***"),
    (_SNMP_USM_USER_LINE, "snmp-agent usm-user *** REDACTED ***"),
    (_NTP_AUTHENTICATION_LINE, "ntp-service authentication-keyid *** REDACTED ***"),
    (_AAA_KEY_LINE, "key authentication/accounting *** REDACTED ***"),
    (_SUPER_PASSWORD_LINE, "super password *** REDACTED ***"),
    (_KEY_STRING_LINE, "key-string *** REDACTED ***"),
    (_WEP_KEY_LINE, "wep key *** REDACTED ***"),
    (_PRESHARED_KEY_LINE, "preshared-key *** REDACTED ***"),
    # Local-user lines must run before the generic password rule so both the
    # username and its credential are removed.
    (
        re.compile(r"(?i)local-user\s+\S+\s+password\s+(?:simple|cipher|hash)?\s*\S+"),
        "local-user *** password ***",
    ),
    # Passwords in various forms
    (re.compile(r"(?i)password\s+(?:simple|cipher|hash)?\s*\S+"), "password ***"),
    (re.compile(r"(?i)set\s+password\s+\S+"), "set password ***"),
    (re.compile(r"(?i)secret\s+\S+"), "secret ***"),
    # Pre-shared keys (IPsec, etc.)
    (re.compile(r"(?i)pre-shared-key\s+(?:simple|cipher)?\s*\S+"), "pre-shared-key ***"),
    # RADIUS/TACACS+ shared secrets
    (
        re.compile(r"(?i)(?:key\s+shared-secret|shared-secret)\s+(?:(?:simple|cipher)\s+)?\S+"),
        "shared-secret ***",
    ),
    # General key patterns run last so they cannot consume a syntax qualifier
    # before one of the complete credential-family rules sees the real secret.
    (re.compile(r"(?i)(?:authentication-)?key\s+(?:simple|cipher)?\s*\S+"), "key ***"),
    # SSH authorized keys
    (re.compile(r"ssh-rsa\s+AAAA[0-9A-Za-z+/]+=*"), "ssh-rsa *** REDACTED ***"),
]


def redact_sensitive(text: str) -> str:
    """Redact sensitive patterns from device output.

    Applies all redaction patterns in order. Each pattern is applied
    once per call to avoid infinite loops.

    Args:
        text: Raw device output (untrusted).

    Returns:
        Sanitized text with sensitive patterns replaced by placeholders.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in REDACT_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def quick_redact(text: str) -> str:
    """Faster redaction for real-time output — only applies
    the highest-priority patterns (password, secret, key).

    This is useful when redacting output line-by-line during
    command execution to minimize latency.
    """
    if not text:
        return text

    quick_patterns: list[tuple[Pattern[str], str]] = [
        (_SNMP_COMMUNITY_LINE, "snmp-agent community *** REDACTED ***"),
        (_SNMP_USM_USER_LINE, "snmp-agent usm-user *** REDACTED ***"),
        (_NTP_AUTHENTICATION_LINE, "ntp-service authentication-keyid *** REDACTED ***"),
        (_AAA_KEY_LINE, "key authentication/accounting *** REDACTED ***"),
        (_SUPER_PASSWORD_LINE, "super password *** REDACTED ***"),
        (_KEY_STRING_LINE, "key-string *** REDACTED ***"),
        (_WEP_KEY_LINE, "wep key *** REDACTED ***"),
        (_PRESHARED_KEY_LINE, "preshared-key *** REDACTED ***"),
        (
            re.compile(r"(?i)local-user\s+\S+\s+password\s+(?:simple|cipher|hash)?\s*\S+"),
            "local-user *** password ***",
        ),
        (re.compile(r"(?i)password\s+(?:simple|cipher|hash)?\s*\S+"), "password ***"),
        (re.compile(r"(?i)secret\s+\S+"), "secret ***"),
        (re.compile(r"(?i)pre-shared-key\s+(?:simple|cipher)?\s*\S+"), "pre-shared-key ***"),
        (re.compile(r"(?i)(?:authentication-)?key\s+(?:simple|cipher)?\s*\S+"), "key ***"),
    ]

    result = text
    for pattern, replacement in quick_patterns:
        result = pattern.sub(replacement, result)

    return result
