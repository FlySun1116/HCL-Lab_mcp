"""Comware device capability matrix.

Maps device model identifiers to their known capabilities.
Used to determine which transport methods and features are available
for a given device type.
"""

from __future__ import annotations

from typing import Any

# Each entry describes what a device model supports.
# Values are conservative — only list capabilities confirmed to work.
CAPABILITIES: dict[str, dict[str, Any]] = {
    "S6850": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "S6820": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "S6520X": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "MSR36-20": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "MSR36-40": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "MSR26-00": {
        "supports_ssh": False,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "S5130": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "S5560": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
    "F1060": {
        "supports_ssh": True,
        "supports_netconf": False,
        "prompt_style": "standard",
        "default_console_speed": 9600,
    },
}


def get_capabilities(model: str) -> dict[str, Any] | None:
    """Return the capability dict for a device model, or None if unknown."""
    return CAPABILITIES.get(model)


def supports_transport(model: str, transport: str) -> bool | None:
    """Check if a model supports a given transport.

    Returns None if the model is unknown, else True/False.
    """
    caps = CAPABILITIES.get(model)
    if caps is None:
        return None
    key = f"supports_{transport}"
    val = caps.get(key, False)
    return bool(val) if val is not None else None
