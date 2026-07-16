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
    # Passwords in various forms
    (re.compile(r"(?i)password\s+(?:simple|cipher|hash)?\s*\S+"), "password ***"),
    (re.compile(r"(?i)set\s+password\s+\S+"), "set password ***"),
    (re.compile(r"(?i)secret\s+\S+"), "secret ***"),
    # SNMP community strings
    (re.compile(r"(?i)snmp-agent\s+community\s+(?:read|write)?\s*\S+"), "snmp-agent community ***"),
    # Local user passwords
    (
        re.compile(r"(?i)local-user\s+\S+\s+password\s+(?:simple|cipher|hash)?\s*\S+"),
        "local-user *** password ***",
    ),
    # Pre-shared keys (IPsec, etc.)
    (re.compile(r"(?i)pre-shared-key\s+(?:simple|cipher)?\s*\S+"), "pre-shared-key ***"),
    # General key patterns (more careful — only match known key contexts)
    (re.compile(r"(?i)(?:authentication-)?key\s+(?:simple|cipher)?\s*\S+"), "key ***"),
    # RADIUS/TACACS+ shared secrets
    (re.compile(r"(?i)(?:key\s+shared-secret|shared-secret)\s+\S+"), "shared-secret ***"),
    (re.compile(r"(?i)key\s+authentication\s+\S+"), "key authentication ***"),
    (re.compile(r"(?i)key\s+accounting\s+\S+"), "key accounting ***"),
    # NTP authentication keys
    (
        re.compile(r"(?i)ntp-service\s+authentication-keyid\s+\d+\s+authentication-mode\s+\S+\s+\S+"),
        "ntp-service authentication-keyid ***",
    ),
    # SNMPv3 syntax varies between Comware releases. Redact the complete line
    # rather than trying to identify only one positional secret.
    (
        re.compile(r"(?im)^\s*snmp-agent\s+usm-user\b[^\r\n]*$"),
        "snmp-agent usm-user *** REDACTED ***",
    ),
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
        (re.compile(r"(?i)password\s+(?:simple|cipher|hash)?\s*\S+"), "password ***"),
        (re.compile(r"(?i)secret\s+\S+"), "secret ***"),
        (
            re.compile(r"(?i)snmp-agent\s+community\s+(?:read|write)?\s*\S+"),
            "snmp-agent community ***",
        ),
        (
            re.compile(r"(?i)local-user\s+\S+\s+password\s+(?:simple|cipher|hash)?\s*\S+"),
            "local-user *** password ***",
        ),
        (re.compile(r"(?i)pre-shared-key\s+(?:simple|cipher)?\s*\S+"), "pre-shared-key ***"),
        (re.compile(r"(?i)(?:authentication-)?key\s+(?:simple|cipher)?\s*\S+"), "key ***"),
    ]

    result = text
    for pattern, replacement in quick_patterns:
        result = pattern.sub(replacement, result)

    return result
