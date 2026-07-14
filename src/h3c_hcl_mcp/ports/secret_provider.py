"""Port: SecretProvider — retrieve secrets without exposing them in code."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SecretProvider(ABC):
    """Retrieve secrets from environment, credential stores, or external vaults.

    Secrets are never logged or returned in plaintext to MCP clients.
    """

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Sources (in priority order):
        1. Environment variable references
        2. System credential store (Windows Credential Manager, etc.)
        3. External vault

        Returns None if the secret is not found.

        Raises:
            DomainError(INTERNAL_ERROR): secret store is unavailable.
        """
        ...
