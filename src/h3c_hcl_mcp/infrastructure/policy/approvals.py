"""ApprovalProvider implementation — HMAC-signed single-use tokens.

Tokens are bound to: caller, plan_id, operation_hash, and expires_at.
Each token can be consumed only once. In-memory storage for v0.1.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import UTC, datetime
from typing import Any

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.approval_provider import ApprovalProvider


class ApprovalProviderImpl(ApprovalProvider):
    """In-memory, HMAC-signed single-use approval tokens."""

    def __init__(self, secret_key: str | None = None) -> None:
        self._secret: bytes = (secret_key or os.urandom(32).hex()).encode("utf-8")
        # In-memory store: token_id -> token metadata
        self._store: dict[str, dict[str, Any]] = {}
        # Consumed token IDs (one-time use enforcement)
        self._consumed: set[str] = set()

    def _make_token_id(self) -> str:
        """Generate a unique token identifier."""
        return hashlib.sha256(os.urandom(32)).hexdigest()[:32]

    def _sign(self, payload: str) -> str:
        """Create an HMAC-SHA256 signature for a payload string."""
        return hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _make_payload(
        self, token_id: str, caller: str, plan_id: str, operation_hash: str, expires_at: int
    ) -> str:
        """Build the signed payload string."""
        return f"{token_id}:{caller}:{plan_id}:{operation_hash}:{expires_at}"

    def _parse_token(self, token: str) -> tuple[str, str, str, str, int, str] | None:
        """Parse a token string and verify signature.

        Token format: token_id:caller:plan_id:operation_hash:expires_at:signature

        Returns (token_id, caller, plan_id, operation_hash, expires_at, signature)
        or None if malformed.
        """
        parts = token.split(":")
        if len(parts) != 6:
            return None
        token_id, caller, plan_id, operation_hash, expires_str, signature = parts
        try:
            expires_at = int(expires_str)
        except ValueError:
            return None
        return token_id, caller, plan_id, operation_hash, expires_at, signature

    async def issue(
        self,
        caller: str,
        plan_id: str,
        operation_hash: str,
        ttl_seconds: int = 300,
    ) -> str:
        """Issue a new HMAC-signed approval token.

        Raises:
            DomainError(POLICY_DENIED): if ttl is invalid.
        """
        if ttl_seconds <= 0 or ttl_seconds > 3600:
            raise DomainError(
                ErrorCode.POLICY_DENIED,
                f"ttl_seconds must be between 1 and 3600, got {ttl_seconds}",
            )

        token_id = self._make_token_id()
        expires_at = int(time.time()) + ttl_seconds
        payload = self._make_payload(token_id, caller, plan_id, operation_hash, expires_at)
        signature = self._sign(payload)
        token = f"{token_id}:{caller}:{plan_id}:{operation_hash}:{expires_at}:{signature}"

        self._store[token_id] = {
            "caller": caller,
            "plan_id": plan_id,
            "operation_hash": operation_hash,
            "expires_at": expires_at,
            "created_at": datetime.now(UTC),
            "consumed": False,
        }

        return token

    async def verify(self, token: str, plan_id: str) -> bool:
        """Verify token is valid, not expired, not consumed, and matches plan_id."""
        parsed = self._parse_token(token)
        if parsed is None:
            return False

        token_id, _caller, tok_plan_id, _op_hash, expires_at, signature = parsed

        # Rebuild payload and verify signature
        payload = self._make_payload(token_id, _caller, tok_plan_id, _op_hash, expires_at)
        expected_sig = self._sign(payload)
        if not hmac.compare_digest(signature, expected_sig):
            return False

        # Check expiry
        if int(time.time()) > expires_at:
            return False

        # Check consumed
        if token_id in self._consumed:
            return False

        # Check plan_id matches
        if tok_plan_id != plan_id:
            return False

        # Check token exists in store
        return token_id in self._store

    async def consume(self, token: str, plan_id: str) -> bool:
        """Consume an approval token (one-time use).

        Returns True if successfully consumed.

        Raises:
            DomainError(APPROVAL_INVALID): token invalid or already consumed.
            DomainError(APPROVAL_EXPIRED): token has expired.
        """
        parsed = self._parse_token(token)
        if parsed is None:
            raise DomainError(ErrorCode.APPROVAL_INVALID, "malformed token")

        token_id, _caller, tok_plan_id, _op_hash, expires_at, signature = parsed

        # Verify signature
        payload = self._make_payload(token_id, _caller, tok_plan_id, _op_hash, expires_at)
        expected_sig = self._sign(payload)
        if not hmac.compare_digest(signature, expected_sig):
            raise DomainError(ErrorCode.APPROVAL_INVALID, "invalid token signature")

        if tok_plan_id != plan_id:
            raise DomainError(ErrorCode.APPROVAL_INVALID, "token does not match plan_id")

        # Check expiry
        if int(time.time()) > expires_at:
            raise DomainError(ErrorCode.APPROVAL_EXPIRED, "token has expired")

        # Check already consumed
        if token_id in self._consumed:
            raise DomainError(ErrorCode.APPROVAL_INVALID, "token already consumed")

        # Mark as consumed
        self._consumed.add(token_id)
        if token_id in self._store:
            self._store[token_id]["consumed"] = True

        return True
