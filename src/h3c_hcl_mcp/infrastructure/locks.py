"""Device session locks — per-device exclusive access for command execution.

Each device (project_id, device_id) gets its own asyncio.Lock.
Commands against the same device are serialized; commands against
different devices run concurrently.
"""

from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class DeviceKey(NamedTuple):
    """Composite key for locking a specific device session."""

    project_id: str
    device_id: int


class DeviceLockManager:
    """Manages per-device session locks.

    Each device gets a single exclusive lock. Commands to the same
    device are serialized. Commands to different devices proceed in parallel.

    Supports acquisition timeout to prevent infinite blocking.
    """

    def __init__(self, max_concurrent: int = 256) -> None:
        self._locks: dict[DeviceKey, asyncio.Lock] = {}
        self._max_concurrent = max_concurrent

    def _get_lock(self, project_id: str, device_id: int) -> asyncio.Lock:
        """Get or create a lock for a device."""
        key = DeviceKey(project_id, device_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def acquire(
        self,
        project_id: str,
        device_id: int,
        timeout_seconds: float = 30.0,
    ) -> bool:
        """Acquire a session lock for a device.

        Returns True if acquired, False on timeout.

        Args:
            project_id: HCL project identifier.
            device_id: Numeric device ID.
            timeout_seconds: Maximum time to wait for the lock.

        Returns:
            True if lock was acquired within the timeout.
        """
        lock = self._get_lock(project_id, device_id)

        try:
            acquired = await asyncio.wait_for(
                lock.acquire(),
                timeout=timeout_seconds,
            )
            if acquired:
                logger.debug(
                    "Lock acquired project=%s device=%d",
                    project_id,
                    device_id,
                )
            return acquired
        except TimeoutError:
            logger.warning(
                "Lock timeout project=%s device=%d timeout=%.1fs",
                project_id,
                device_id,
                timeout_seconds,
            )
            return False

    def release(self, project_id: str, device_id: int) -> None:
        """Release a previously acquired session lock.

        Safe to call even if the lock was not acquired (no-op).
        """
        key = DeviceKey(project_id, device_id)
        lock = self._locks.get(key)
        if lock is not None and lock.locked():
            lock.release()
            logger.debug(
                "Lock released project=%s device=%d",
                project_id,
                device_id,
            )

    @property
    def active_locks(self) -> int:
        """Number of currently held locks."""
        return sum(1 for lock in self._locks.values() if lock.locked())

    def cleanup_idle(self, max_idle_seconds: float = 600.0) -> int:
        """Remove lock entries that have been idle (no waiters, not locked)
        for more than max_idle_seconds.

        This prevents unbounded memory growth for devices that are
        no longer in use. Returns number of entries removed.
        """
        to_remove = []
        for key, lock in self._locks.items():
            if not lock.locked() and not lock._waiters:  # type: ignore[attr-defined]
                to_remove.append(key)

        for key in to_remove:
            del self._locks[key]

        if to_remove:
            logger.debug("Cleaned up %d idle lock entries", len(to_remove))
        return len(to_remove)

    async def __aenter__(self) -> DeviceLockManager:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass
