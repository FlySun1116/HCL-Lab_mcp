"""Comware device session management with exclusive per-device lock.

Each device gets a single DeviceSession that tracks state and serializes
access through an asyncio.Lock. No two commands execute concurrently on
the same device.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from h3c_hcl_mcp.adapters.comware.base import SessionState


@dataclass
class DeviceSession:
    """Per-device session tracking and exclusive lock.

    The lock ensures only one command executes at a time on a given device.
    State transitions follow: DISCONNECTED -> CONNECTING -> READY <-> BUSY -> CLOSING.
    """

    device_id: int
    device_name: str
    state: SessionState = SessionState.DISCONNECTED
    last_active: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _reconnect_attempts: int = field(default=0, repr=False)

    # ---- State queries ----

    @property
    def is_ready(self) -> bool:
        """Session is connected and idle, ready for a command."""
        return self.state == SessionState.READY

    @property
    def is_busy(self) -> bool:
        """Session is currently executing a command."""
        return self.state == SessionState.BUSY

    @property
    def is_connected(self) -> bool:
        """Session has an active transport connection."""
        return self.state in (SessionState.READY, SessionState.BUSY)

    def touch(self) -> None:
        """Update last-active timestamp to now."""
        self.last_active = time.monotonic()

    def reset_reconnect(self) -> None:
        """Reset the reconnect counter after a successful connection."""
        self._reconnect_attempts = 0
