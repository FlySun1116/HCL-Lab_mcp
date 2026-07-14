"""Port: JobStore — track long-running asynchronous jobs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStore(ABC):
    """Persistent store for async job status and results."""

    @abstractmethod
    async def create(self, job_type: str, target: dict[str, Any] | None = None) -> str:
        """Create a new job and return its ID."""
        ...

    @abstractmethod
    async def update(
        self,
        job_id: str,
        status: JobStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Update job status and optionally set result/error."""
        ...

    @abstractmethod
    async def get(self, job_id: str) -> dict[str, Any]:
        """Get current job state.

        Returns dict with keys: job_id, type, status, result, error, created_at, updated_at.

        Raises:
            DomainError(NOT_FOUND): job_id does not exist.
        """
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Request cancellation of a job.

        Returns True if the job was successfully cancelled.
        Jobs in non-cancellable states return False.
        """
        ...
