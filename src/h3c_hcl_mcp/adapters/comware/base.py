"""Comware adapter base types and exceptions.

All Comware-specific errors inherit from ComwareError.
Session state enum tracks the lifecycle of a device session.
"""

from __future__ import annotations

from enum import StrEnum


class SessionState(StrEnum):
    """Comware device session lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    BUSY = "busy"
    CLOSING = "closing"


class ComwareError(Exception):
    """Base exception for Comware adapter errors.

    Subclasses map specific failure modes to domain ErrorCode values.
    """

    pass


class ComwareConnectionError(ComwareError):
    """Failed to establish or lost a transport connection."""

    pass


class ComwarePromptError(ComwareError):
    """Prompt detection or timeout failure."""

    pass


class ComwareCommandError(ComwareError):
    """Command execution failure on the device."""

    pass
