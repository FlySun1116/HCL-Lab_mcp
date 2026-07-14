"""Configuration loading from multiple sources.

Priority (highest to lowest):
1. CLI arguments
2. H3C_HCL_MCP__* environment variables
3. YAML/JSON config file
4. Defaults

All settings are validated via Pydantic models.
"""

from __future__ import annotations

import json
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration directory
# ---------------------------------------------------------------------------


def _default_config_dir() -> Path:
    """Return the default configuration directory.

    Windows: %LOCALAPPDATA%\\h3c-hcl-mcp
    Other: ~/.config/h3c-hcl-mcp
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "h3c-hcl-mcp"
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(base) / "h3c-hcl-mcp"


# ---------------------------------------------------------------------------
# Settings models
# ---------------------------------------------------------------------------


class TransportMode(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class PolicyMode(StrEnum):
    READ_ONLY = "read_only"
    CONTROLLED_WRITE = "controlled_write"
    LAB_ADMIN = "lab_admin"


class ServerSettings(BaseModel):
    """MCP server operational settings."""

    name: str = "h3c-hcl-mcp"
    transport: TransportMode = TransportMode.STDIO
    log_level: str = "INFO"
    max_tool_seconds: int = Field(default=60, ge=1, le=600)
    max_output_chars: int = Field(default=32768, ge=256, le=1048576)
    config_dir: str = Field(default_factory=lambda: str(_default_config_dir()))


class PolicySettings(BaseModel):
    """Security policy settings."""

    mode: PolicyMode = PolicyMode.READ_ONLY
    require_approval_for_writes: bool = True
    plan_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    approval_token_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    max_concurrent_sessions: int = Field(default=32, ge=1, le=256)
    session_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    max_commands_per_session: int = Field(default=100, ge=1, le=1000)


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

_ENV_PREFIX = "H3C_HCL_MCP__"


def _load_from_env() -> dict[str, Any]:
    """Extract settings from environment variables.

    Maps H3C_HCL_MCP__SERVER__NAME -> {"server": {"name": "..."}}
    Supports up to 2 levels of nesting via double-underscore separator.
    """
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        # Strip prefix and lowercase
        stripped = key[len(_ENV_PREFIX) :].lower()
        parts = stripped.split("__")
        if len(parts) == 1:
            # Flat key: H3C_HCL_MCP__LOG_LEVEL
            result[parts[0]] = _coerce_value(value)
        elif len(parts) == 2:
            # Nested key: H3C_HCL_MCP__SERVER__NAME
            section, field = parts
            if section not in result:
                result[section] = {}
            result[section][field] = _coerce_value(value)
    return result


def _coerce_value(value: str) -> int | float | bool | str:
    """Coerce string env var to the most appropriate Python type."""
    # Bool
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Int
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_config_file(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from a JSON or YAML file.

    If YAML support is available (pyyaml installed), YAML files are
    supported. Otherwise, only JSON is supported.

    Default search paths:
    1. Explicit path passed to this function
    2. H3C_HCL_MCP_CONFIG environment variable
    3. {config_dir}/config.json
    """
    if config_path is None:
        config_path = os.environ.get("H3C_HCL_MCP_CONFIG")

    if config_path:
        paths = [Path(config_path)]
    else:
        config_dir = _default_config_dir()
        paths = [
            config_dir / "config.json",
            config_dir / "config.yaml",
            config_dir / "config.yml",
        ]

    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except (OSError, PermissionError):
            continue

        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return _parse_yaml(raw)
        elif suffix == ".json":
            result: dict[str, Any] = json.loads(raw)
            return result

    return {}


def _parse_yaml(raw: str) -> dict[str, Any]:
    """Parse YAML content if PyYAML is available."""
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml.safe_load(raw) or {}
    except ImportError:
        # YAML not available; return empty
        return {}
    except Exception:
        return {}


def load_server_settings(
    cli_args: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> ServerSettings:
    """Load and merge ServerSettings from all sources.

    Priority: CLI args > env vars > config file > defaults
    """
    merged: dict[str, Any] = {}

    # Layer 4: Defaults (already in the model, so empty dict is fine)
    # Layer 3: Config file
    config_data = _load_config_file(config_path)
    server_config = config_data.get("server", {})
    if isinstance(server_config, dict):
        merged.update(server_config)

    # Layer 2: Environment variables
    env_data = _load_from_env()
    server_env = env_data.get("server", {})
    if isinstance(server_env, dict):
        merged.update(server_env)

    # Layer 1: CLI arguments (highest priority)
    if cli_args:
        cli_server = cli_args.get("server", cli_args)
        if isinstance(cli_server, dict):
            merged.update(cli_server)

    return ServerSettings(**merged)


def load_policy_settings(
    cli_args: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> PolicySettings:
    """Load and merge PolicySettings from all sources.

    Priority: CLI args > env vars > config file > defaults
    """
    merged: dict[str, Any] = {}

    # Layer 3: Config file
    config_data = _load_config_file(config_path)
    policy_config = config_data.get("policy", {})
    if isinstance(policy_config, dict):
        merged.update(policy_config)

    # Layer 2: Environment variables
    env_data = _load_from_env()
    policy_env = env_data.get("policy", {})
    if isinstance(policy_env, dict):
        merged.update(policy_env)

    # Layer 1: CLI arguments (highest priority)
    if cli_args:
        cli_policy = cli_args.get("policy", {})
        if isinstance(cli_policy, dict):
            merged.update(cli_policy)

    return PolicySettings(**merged)


def ensure_config_dir() -> Path:
    """Ensure the configuration directory exists, creating it if needed."""
    config_dir = _default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
