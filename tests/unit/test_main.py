"""Unit tests for the stdio CLI entry point."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import h3c_hcl_mcp.__main__ as cli
import h3c_hcl_mcp.infrastructure.logging as logging_module
import h3c_hcl_mcp.infrastructure.settings as settings_module
from h3c_hcl_mcp.adapters.comware.session_manager import DeviceSessionManager
from h3c_hcl_mcp.mcp.server import SERVER_NAME, create_server
from h3c_hcl_mcp.version import VERSION


def test_parse_args_defaults() -> None:
    args = cli._parse_args([])

    assert args.config is None
    assert args.projects_dirs is None


def test_parse_args_accepts_config_and_repeated_project_dirs(tmp_path: Any) -> None:
    config = tmp_path / "config.yaml"
    first = tmp_path / "projects-a"
    second = tmp_path / "projects-b"

    args = cli._parse_args(
        [
            "--config",
            str(config),
            "--projects-dir",
            str(first),
            "--projects-dir",
            str(second),
        ]
    )

    assert args.config == str(config)
    assert args.projects_dirs == [str(first), str(second)]


def test_parse_args_version_exits_without_starting_server(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._parse_args(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out.strip() == f"{SERVER_NAME} v{VERSION}"
    assert captured.err == ""


def test_parse_args_rejects_unknown_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._parse_args(["--unknown-option"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert captured.out == ""
    assert "unrecognized arguments: --unknown-option" in captured.err


def test_module_execution_supports_version_without_loading_user_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module_path = Path(cli.__file__)
    monkeypatch.setattr(sys, "argv", [str(module_path), "--version"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(module_path), run_name="__main__")

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out.strip() == f"{SERVER_NAME} v{VERSION}"
    assert captured.err == ""


def test_main_loads_overrides_configures_logging_and_runs_stdio(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
) -> None:
    config = tmp_path / "config.json"
    project_dir = tmp_path / "projects"
    settings = SimpleNamespace(server=SimpleNamespace(name="test-mcp", log_level="DEBUG"))
    calls: dict[str, Any] = {}

    def fake_load_settings(*, cli_args: object, config_path: str | None) -> object:
        calls["load"] = (cli_args, config_path)
        return settings

    def fake_setup_logging(level: str) -> None:
        calls["log_level"] = level

    class FakeServer:
        async def run_stdio_async(self) -> None:
            calls["stdio_run"] = True

    def fake_create_server(*, settings: object) -> FakeServer:
        calls["server_settings"] = settings
        return FakeServer()

    monkeypatch.setattr(settings_module, "load_settings", fake_load_settings)
    monkeypatch.setattr(logging_module, "setup_logging", fake_setup_logging)
    monkeypatch.setattr(cli, "create_server", fake_create_server)

    cli.main(
        [
            "--config",
            str(config),
            "--projects-dir",
            str(project_dir),
        ]
    )

    captured = capsys.readouterr()
    assert calls["load"] == ({"hcl": {"projects_dirs": [str(project_dir)]}}, str(config))
    assert calls["log_level"] == "DEBUG"
    assert calls["server_settings"] is settings
    assert calls["stdio_run"] is True
    assert captured.out == ""
    assert captured.err.strip() == f"test-mcp v{VERSION} -- starting stdio server..."


def test_main_passes_no_cli_overrides_and_propagates_settings_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = RuntimeError("synthetic settings failure")
    calls: dict[str, object] = {}

    def fake_load_settings(*, cli_args: object, config_path: str | None) -> object:
        calls["load"] = (cli_args, config_path)
        raise expected

    monkeypatch.setattr(settings_module, "load_settings", fake_load_settings)

    with pytest.raises(RuntimeError) as exc_info:
        cli.main([])

    assert exc_info.value is expected
    assert calls["load"] == (None, None)


def test_main_propagates_stdio_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = SimpleNamespace(server=SimpleNamespace(name="test-mcp", log_level="INFO"))
    expected = RuntimeError("synthetic stdio failure")

    class FailingServer:
        async def run_stdio_async(self) -> None:
            raise expected

    monkeypatch.setattr(settings_module, "load_settings", lambda **_: settings)
    monkeypatch.setattr(logging_module, "setup_logging", lambda _: None)
    monkeypatch.setattr(cli, "create_server", lambda **_: FailingServer())

    with pytest.raises(RuntimeError) as exc_info:
        cli.main([])

    captured = capsys.readouterr()
    assert exc_info.value is expected
    assert captured.out == ""
    assert captured.err.strip() == f"test-mcp v{VERSION} -- starting stdio server..."


async def test_server_lifespan_closes_all_device_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls = 0

    async def tracked_close_all(self: DeviceSessionManager) -> None:
        nonlocal close_calls
        close_calls += 1

    monkeypatch.setattr(DeviceSessionManager, "close_all", tracked_close_all)
    server = create_server()

    async with server._mcp_server.lifespan(server._mcp_server):
        assert close_calls == 0

    assert close_calls == 1
