"""SecretProvider implementation — multi-source secret resolution.

Secrets are never logged, stored in plaintext, or returned in raw
form to MCP clients. This module retrieves secrets from:
1. Environment variables (priority)
2. JSON secret file
3. System credential store (placeholder — platform-specific impl TBD)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.secret_provider import SecretProvider

logger = logging.getLogger(__name__)


class SecretProviderImpl(SecretProvider):
    """Multi-source secret provider.

    Priority (highest to lowest):
    1. Environment variables
    2. JSON secrets file
    3. System credential store (placeholder for v0.2)

    All retrieval is done on-demand; secrets are never cached in memory.
    """

    def __init__(self, secrets_file: str | None = None) -> None:
        self._secrets_file: Path | None = Path(secrets_file) if secrets_file else None
        self._cache: dict[str, str | None] = {}

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Returns None if the secret is not found in any source.

        Raises:
            DomainError(INTERNAL_ERROR): secret store is unavailable
                due to filesystem errors (not missing secrets).
        """
        # 1. Environment variable
        env_value = self._from_env(key)
        if env_value is not None:
            return env_value

        # 2. JSON secrets file
        file_value = await self._from_file(key)
        if file_value is not None:
            return file_value

        # 3. System credential store (placeholder)
        store_value = await self._from_credential_store(key)
        if store_value is not None:
            return store_value

        return None

    def _from_env(self, key: str) -> str | None:
        """Look up a secret from environment variables.

        Maps key -> H3C_HCL_SECRET_{UPPER_KEY}
        e.g., "hcl_api_token" -> H3C_HCL_SECRET_HCL_API_TOKEN
        """
        env_name = f"H3C_HCL_SECRET_{key.upper().replace('.', '_')}"
        value = os.environ.get(env_name)
        if value:
            logger.debug("Secret '%s' resolved from env var %s", key, env_name)
        return value

    async def _from_file(self, key: str) -> str | None:
        """Look up a secret from a JSON secrets file.

        File path is set at construction time or from
        H3C_HCL_SECRETS_FILE env var.
        """
        secrets_path = self._secrets_file
        if secrets_path is None:
            env_path = os.environ.get("H3C_HCL_SECRETS_FILE")
            if env_path:
                secrets_path = Path(env_path)

        if secrets_path is None or not secrets_path.exists():
            return None

        try:
            raw = secrets_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            raise DomainError(
                ErrorCode.INTERNAL_ERROR,
                f"secrets file is not valid JSON: {e}",
            ) from e
        except OSError as e:
            raise DomainError(
                ErrorCode.INTERNAL_ERROR,
                f"cannot read secrets file: {e}",
            ) from e

        value = data.get(key)
        if value is not None and isinstance(value, str):
            logger.debug("Secret '%s' resolved from file %s", key, secrets_path)
            return value
        return None

    async def _from_credential_store(self, key: str) -> str | None:
        """Look up a secret from the system credential store.

        PLACEHOLDER for v0.2 — not yet implemented.
        Will use keyring library or platform-specific APIs.
        """
        # TODO(v0.2): Integrate with Windows Credential Manager,
        # macOS Keychain, or freedesktop Secret Service.
        return None
