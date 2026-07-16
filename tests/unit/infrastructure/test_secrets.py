"""Tests for isolated, non-leaking secret resolution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.secrets import SecretProviderImpl


@pytest.mark.asyncio
async def test_environment_secret_has_priority_and_value_is_not_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    env_value = "env-value-that-must-not-be-logged"
    file_value = "file-value-that-must-not-be-returned"
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps({"device.password": file_value}), encoding="utf-8")
    monkeypatch.setenv("H3C_HCL_SECRET_DEVICE_PASSWORD", env_value)
    caplog.set_level(logging.DEBUG, logger="h3c_hcl_mcp.infrastructure.secrets")

    result = await SecretProviderImpl(str(secrets_file)).get_secret("device.password")

    assert result == env_value
    assert env_value not in caplog.text
    assert file_value not in caplog.text
    assert "H3C_HCL_SECRET_DEVICE_PASSWORD" in caplog.text


@pytest.mark.asyncio
async def test_explicit_file_precedes_environment_file_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    explicit_file = tmp_path / "explicit.json"
    environment_file = tmp_path / "environment.json"
    explicit_file.write_text(json.dumps({"token": "explicit-value"}), encoding="utf-8")
    environment_file.write_text(json.dumps({"token": "environment-value"}), encoding="utf-8")
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)
    monkeypatch.setenv("H3C_HCL_SECRETS_FILE", str(environment_file))

    result = await SecretProviderImpl(str(explicit_file)).get_secret("token")

    assert result == "explicit-value"


@pytest.mark.asyncio
async def test_environment_file_path_is_used_without_constructor_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / "environment.json"
    secrets_file.write_text(json.dumps({"token": "file-value"}), encoding="utf-8")
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)
    monkeypatch.setenv("H3C_HCL_SECRETS_FILE", str(secrets_file))

    result = await SecretProviderImpl().get_secret("token")

    assert result == "file-value"


@pytest.mark.asyncio
async def test_empty_environment_value_is_an_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps({"token": "file-value"}), encoding="utf-8")
    monkeypatch.setenv("H3C_HCL_SECRET_TOKEN", "")

    result = await SecretProviderImpl(str(secrets_file)).get_secret("token")

    assert result == ""


@pytest.mark.asyncio
async def test_non_string_file_value_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps({"token": 123}), encoding="utf-8")
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)

    result = await SecretProviderImpl(str(secrets_file)).get_secret("token")

    assert result is None


@pytest.mark.asyncio
async def test_missing_sources_fall_back_to_credential_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = SecretProviderImpl(str(tmp_path / "missing.json"))
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)
    calls: list[str] = []

    async def fake_credential_store(key: str) -> str | None:
        calls.append(key)
        return "credential-value"

    monkeypatch.setattr(provider, "_from_credential_store", fake_credential_store)

    result = await provider.get_secret("token")

    assert result == "credential-value"
    assert calls == ["token"]


@pytest.mark.asyncio
async def test_missing_secret_returns_none_without_touching_user_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)
    monkeypatch.delenv("H3C_HCL_SECRETS_FILE", raising=False)

    assert await SecretProviderImpl().get_secret("token") is None


@pytest.mark.asyncio
async def test_invalid_json_raises_sanitized_domain_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_marker = "raw-secret-marker"
    secrets_file = tmp_path / "invalid.json"
    secrets_file.write_text(f'{{"token": "{secret_marker}"', encoding="utf-8")
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)

    with pytest.raises(DomainError) as exc_info:
        await SecretProviderImpl(str(secrets_file)).get_secret("token")

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
    assert "secrets file is not valid JSON" in exc_info.value.message
    assert secret_marker not in exc_info.value.message


@pytest.mark.asyncio
async def test_file_read_error_is_mapped_to_domain_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("H3C_HCL_SECRET_TOKEN", raising=False)

    def deny_read(self: Path, *args: object, **kwargs: object) -> str:
        del self, args, kwargs
        raise OSError("synthetic access denied")

    monkeypatch.setattr(Path, "read_text", deny_read)

    with pytest.raises(DomainError) as exc_info:
        await SecretProviderImpl(str(secrets_file)).get_secret("token")

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
    assert exc_info.value.message == "cannot read secrets file: synthetic access denied"


@pytest.mark.asyncio
async def test_placeholder_credential_store_returns_none() -> None:
    provider = SecretProviderImpl()

    assert await provider._from_credential_store("token") is None
