"""Port: ApprovalProvider — issue, verify, and consume approval tokens."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ApprovalProvider(ABC):
    """Manages short-lived approval tokens for configuration changes.

    Tokens are bound to a specific caller, target, operation hash, and expiry.
    """

    @abstractmethod
    async def issue(
        self,
        caller: str,
        plan_id: str,
        operation_hash: str,
        ttl_seconds: int = 300,
    ) -> str:
        """Issue an approval token for a change plan.

        Returns the token string.

        Raises:
            DomainError(POLICY_DENIED): caller not authorized to approve.
        """
        ...

    @abstractmethod
    async def verify(self, token: str, plan_id: str) -> bool:
        """Verify that a token is valid for the given plan.

        Returns True if valid, not expired, and not yet consumed.
        """
        ...

    @abstractmethod
    async def consume(self, token: str, plan_id: str) -> bool:
        """Consume an approval token, making it single-use.

        Returns True if successfully consumed.

        Raises:
            DomainError(APPROVAL_INVALID): token invalid or already consumed.
            DomainError(APPROVAL_EXPIRED): token has expired.
        """
        ...
