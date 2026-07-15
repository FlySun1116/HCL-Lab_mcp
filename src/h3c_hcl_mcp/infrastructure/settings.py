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

from pydantic import BaseModel, ConfigDict, Field

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


def _default_config_paths() -> list[Path]:
    """Return the default configuration file search paths in priority order."""
    config_dir = _default_config_dir()
    return [
        config_dir / "config.yaml",
        config_dir / "config.yml",
        config_dir / "config.json",
    ]


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

    model_config = ConfigDict(extra="forbid")

    name: str = "h3c-hcl-mcp"
    transport: TransportMode = TransportMode.STDIO
    log_level: str = "INFO"
    max_tool_seconds: int = Field(default=60, ge=1, le=600)
    max_output_chars: int = Field(default=32768, ge=256, le=1048576)
    config_dir: str = Field(default_factory=lambda: str(_default_config_dir()))


class PolicySettings(BaseModel):
    """Security policy settings."""

    model_config = ConfigDict(extra="forbid")

    mode: PolicyMode = PolicyMode.READ_ONLY
    require_approval_for_writes: bool = True
    plan_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    approval_token_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    max_concurrent_sessions: int = Field(default=32, ge=1, le=256)
    session_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    max_commands_per_session: int = Field(default=100, ge=1, le=1000)
    allow_display_prefixes: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)


class HCLRuntimeDiscoverySettings(BaseModel):
    """HCL runtime discovery configuration."""

    model_config = ConfigDict(extra="forbid")

    process_inspection: bool = True
    log_observation: bool = True
    loopback_probe: bool = True
    console_host: str = "127.0.0.1"
    fallback_telnet_base: int = Field(default=30000, ge=1024, le=65535)
    max_probe_ports: int = Field(default=32, ge=1, le=256)


class PrivateControlAPISettings(BaseModel):
    """HCL private control API — disabled by default, requires H3C authorization."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


class HCLDiscoverySettings(BaseModel):
    """HCL project discovery and runtime settings."""

    model_config = ConfigDict(extra="forbid")

    projects_dirs: list[str] = Field(default_factory=list)
    install_dir: str | None = None
    supported_versions: list[str] = Field(default_factory=lambda: ["5.10.*"])
    runtime_discovery: HCLRuntimeDiscoverySettings = Field(default_factory=HCLRuntimeDiscoverySettings)
    private_control_api: PrivateControlAPISettings = Field(default_factory=PrivateControlAPISettings)


class SSHSettings(BaseModel):
    """SSH connection settings."""

    model_config = ConfigDict(extra="forbid")

    username_env: str = "H3C_HCL_MCP_SSH_USERNAME"
    password_env: str = "H3C_HCL_MCP_SSH_PASSWORD"
    known_hosts: str = ""


class DeviceSettings(BaseModel):
    """Device transport and connection settings."""

    model_config = ConfigDict(extra="forbid")

    preferred_transports: list[str] = Field(default_factory=lambda: ["console_telnet", "ssh"])
    connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    command_timeout_seconds: int = Field(default=20, ge=1, le=300)
    per_device_concurrency: int = Field(default=1, ge=1, le=8)
    ssh: SSHSettings = Field(default_factory=SSHSettings)


class AuditSettings(BaseModel):
    """Audit trail configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    database: str = ""
    retention_days: int = Field(default=90, ge=1, le=365)
    store_raw_device_output: bool = False


class HCLSettings(BaseModel):
    """Root settings model — single configuration entry point."""

    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    hcl: HCLDiscoverySettings = Field(default_factory=HCLDiscoverySettings)
    devices: DeviceSettings = Field(default_factory=DeviceSettings)
    policy: PolicySettings = Field(default_factory=PolicySettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

_ENV_PREFIX = "H3C_HCL_MCP__"


def _load_from_env() -> dict[str, Any]:
    """Extract settings from environment variables.

    Maps H3C_HCL_MCP__SERVER__NAME -> {"server": {"name": "..."}}
    Supports arbitrary nesting via double-underscore separator.

    Examples:
      H3C_HCL_MCP__SERVER__LOG_LEVEL -> {"server": {"log_level": "INFO"}}
      H3C_HCL_MCP__HCL__RUNTIME_DISCOVERY__CONSOLE_HOST ->
        {"hcl": {"runtime_discovery": {"console_host": "..."}}}
    """
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        stripped = key[len(_ENV_PREFIX) :].lower()
        parts = stripped.split("__")
        # Navigate into nested dict, creating levels as needed
        current: dict[str, Any] = result
        skip = False
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                skip = True
                break
            next_level = current[part]
            if isinstance(next_level, dict):
                current = next_level
            else:
                skip = True
                break
        if not skip:
            current[parts[-1]] = _coerce_value(value)
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


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dicts, with overlay values taking precedence.

    Nested dicts are merged recursively. Lists and scalars from overlay
    replace those in base.
    """
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_file_strict(path: Path) -> dict[str, Any]:
    """Load a YAML or JSON config file with strict error handling.

    Args:
        path: Path to the config file.

    Returns:
        Parsed configuration dict.

    Raises:
        SystemExit: If the file cannot be read, parsed, or has invalid content.
    """
    suffix = path.suffix.lower()

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, PermissionError) as e:
        print(f"ERROR: Cannot read configuration file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

    if suffix in (".yaml", ".yml"):
        result = _parse_yaml_strict(raw, path)
    elif suffix == ".json":
        result = _parse_json_strict(raw, path)
    else:
        print(
            f"ERROR: Unsupported configuration file format: '{path}'. Use .yaml, .yml, or .json.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(result, dict):
        print(
            f"ERROR: Configuration file '{path}' must contain a mapping (object) at the top level.",
            file=sys.stderr,
        )
        sys.exit(1)

    return result


def _parse_yaml_strict(raw: str, path: Path) -> dict[str, Any]:
    """Parse YAML content with clear error messages on failure."""
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: YAML configuration requires the 'pyyaml' package. "
            "Install with: pip install pyyaml  or  uv add pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = yaml.safe_load(raw)
    except Exception as e:
        print(
            f"ERROR: Failed to parse YAML configuration '{path}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if data is None:
        return {}
    result: dict[str, Any] = data
    return result


def _parse_json_strict(raw: str, path: Path) -> dict[str, Any]:
    """Parse JSON content with clear error messages on failure."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"ERROR: Failed to parse JSON configuration '{path}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(data, dict):
        print(
            f"ERROR: Configuration file '{path}' must contain a JSON object at the top level.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


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
        import yaml

        return yaml.safe_load(raw) or {}
    except ImportError:
        # YAML not available; return empty
        return {}
    except Exception:
        return {}


def _try_default_config() -> dict[str, Any] | None:
    """Try to load configuration from default search paths.

    Returns the parsed config dict if a file is found, None otherwise.
    """
    for path in _default_config_paths():
        if path.exists():
            return _load_file_strict(path)
    return None


def load_settings(
    cli_args: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> HCLSettings:
    """Unified entry point for loading all settings.

    Priority (highest to lowest):
    1. CLI arguments
    2. H3C_HCL_MCP__* environment variables
    3. YAML/JSON config file
    4. Model defaults

    Args:
        cli_args: Optional dict of CLI overrides (top priority).
        config_path: Optional explicit path to a YAML or JSON config file.
                     If omitted, searches default locations.

    Returns:
        Fully validated HCLSettings instance.

    Raises:
        SystemExit: On missing/malformed config, or unknown fields.
    """
    # --- Layer 3: Config file ---
    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            print(
                f"ERROR: Configuration file not found: {path}",
                file=sys.stderr,
            )
            sys.exit(1)
        config_data = _load_file_strict(path)
    else:
        config_data = _try_default_config()
        if config_data is None:
            default_paths = _default_config_paths()
            print(
                "ERROR: No configuration file found.\n"
                "Place a config.yaml or config.json in one of these locations:\n  "
                + "\n  ".join(str(p) for p in default_paths)
                + "\n\nOr use --config FILE to specify a path.",
                file=sys.stderr,
            )
            sys.exit(1)

    # --- Layer 2: Environment variables ---
    merged = config_data
    env_data = _load_from_env()
    if env_data:
        merged = _deep_merge(merged, env_data)

    # --- Layer 1: CLI arguments (highest priority) ---
    if cli_args:
        merged = _deep_merge(merged, cli_args)

    # --- Validate and return ---
    try:
        return HCLSettings(**merged)
    except Exception as e:
        # Pydantic v2: ValidationError.errors() is a method, not a property
        errors = getattr(e, "errors", None)
        if callable(errors):
            errors = errors()
        if errors is not None:
            for err in errors:
                loc = " -> ".join(str(part) for part in err.get("loc", []))
                msg = err.get("msg", str(err))
                print(f"ERROR: Invalid configuration at '{loc}': {msg}", file=sys.stderr)
        else:
            print(f"ERROR: Invalid configuration: {e}", file=sys.stderr)
        sys.exit(1)


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


def load_config_file(path: str) -> dict[str, object]:
    """Load settings from a specific config file.

    Args:
        path: Path to a YAML or JSON config file.

    Returns:
        Merged settings dict, or empty dict on error.
    """
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            raw = f.read()
    except (OSError, PermissionError):
        return {}

    suffix = config_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        parsed = _parse_yaml(raw)
    elif suffix == ".json":
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}
    else:
        return {}

    return _flatten_config(parsed)


def load_settings_from_env() -> dict[str, object]:
    """Load settings from environment variables.

    Reads H3C_HCL_MCP__* vars and converts to nested dict.
    """
    result: dict[str, object] = {}
    import os

    for key, value in os.environ.items():
        if not key.startswith("H3C_HCL_MCP__"):
            continue
        config_key = key[len("H3C_HCL_MCP__") :].lower()
        result[config_key] = value
    return result


def _flatten_config(data: dict[str, object], prefix: str = "") -> dict[str, object]:
    """Flatten nested config dict to a flat dict."""
    result: dict[str, object] = {}
    for key, value in data.items():
        flat_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict) and not any(isinstance(v, (list, dict)) for v in value.values()):
            for sub_key, sub_value in value.items():
                result[f"{key}_{sub_key}"] = sub_value
        elif isinstance(value, dict):
            result.update(_flatten_config(value, flat_key))
        else:
            result[flat_key] = value
    return result
