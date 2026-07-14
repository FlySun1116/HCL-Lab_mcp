"""Port: AuditSink — append and query audit events."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from h3c_hcl_mcp.domain.audit import AuditEvent


class AuditSink(ABC):
    """Persistent, append-only audit trail for all tool invocations."""

    @abstractmethod
    async def append(self, event: AuditEvent) -> None:
        """Record an audit event."""
        ...

    @abstractmethod
    async def query(
        self,
        request_id: str | None = None,
        tool: str | None = None,
        target_device: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters.

        Returns events in reverse chronological order.
        """
        ...
