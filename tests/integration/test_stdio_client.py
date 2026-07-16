"""Black-box stdio tests using the official MCP Python client.

Unlike the in-process integration tests, this module launches the installed
console entry point (or the source module during development) in a child
process and therefore covers CLI settings, stdout framing, the protocol
handler, and process shutdown together.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from h3c_hcl_mcp.version import VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOL_NAMES = {
    "server_health",
    "hcl_list_projects",
    "hcl_get_topology",
    "hcl_get_runtime",
    "h3c_list_devices",
    "h3c_get_facts",
    "h3c_run_display",
    "h3c_get_config",
    "h3c_get_interfaces",
    "h3c_ping",
    "h3c_trace_route",
    "h3c_diff_config",
    "job_get",
    "job_cancel",
    "audit_query",
}


def _server_launch(tmp_path: Path) -> tuple[str, list[str], bool, Path]:
    """Return command, argument prefix, installation mode, and child cwd."""

    executable = os.environ.get("H3C_HCL_MCP_TEST_EXECUTABLE")
    if executable:
        return executable, [], True, tmp_path
    server_python = os.environ.get("H3C_HCL_MCP_TEST_PYTHON", sys.executable)
    installed = "H3C_HCL_MCP_TEST_PYTHON" in os.environ
    return server_python, ["-m", "h3c_hcl_mcp"], installed, (tmp_path if installed else REPOSITORY_ROOT)


def _isolated_environment(tmp_path: Path, *, include_source_tree: bool) -> dict[str, str]:
    """Build a child environment that cannot consume the user's MCP config."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("H3C_HCL_MCP") and key != "H3C_CLOUD_LAB_PROJECTS"
    }
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    env.update(
        {
            "H3C_HCL_MCP_CONFIG": "",
            "H3C_HCL_MCP__AUDIT__DATABASE": str(tmp_path / "audit.db"),
            "H3C_CLOUD_LAB_PROJECTS": str(projects_dir),
            "LOCALAPPDATA": str(tmp_path / "localappdata"),
            "USERPROFILE": str(tmp_path / "profile"),
        }
    )
    if include_source_tree:
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(REPOSITORY_ROOT / "src"), env.get("PYTHONPATH", "")) if part
        )
    else:
        env.pop("PYTHONPATH", None)
    return env


def _structured_error(result: Any) -> dict[str, Any]:
    assert result.isError is True
    assert result.content
    text = getattr(result.content[0], "text", None)
    assert isinstance(text, str)
    payload = json.loads(text[text.index("{") :])
    error = payload.get("error")
    assert isinstance(error, dict)
    return error


async def test_stdio_server_protocol_and_validation(tmp_path: Path) -> None:
    """A no-config child process must serve clean JSON-RPC over stdout."""
    stderr_path = tmp_path / "server.stderr.log"
    command, argument_prefix, installed, child_cwd = _server_launch(tmp_path)
    parameters = StdioServerParameters(
        command=command,
        args=argument_prefix,
        cwd=child_cwd,
        env=_isolated_environment(tmp_path, include_source_tree=not installed),
        encoding="utf-8",
        encoding_error_handler="replace",
    )

    # Windows subprocess creation requires a real file descriptor for stderr;
    # StringIO cannot be inherited by the child process.
    with stderr_path.open("w+", encoding="utf-8") as stderr:
        async with asyncio.timeout(30):
            async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "h3c-hcl-mcp"
                    assert initialized.serverInfo.version == VERSION

                    listed = await session.list_tools()
                    tool_names = {tool.name for tool in listed.tools}
                    assert tool_names == EXPECTED_TOOL_NAMES

                    health = await session.call_tool("server_health", {"deep": False})
                    assert health.isError is not True
                    assert isinstance(health.structuredContent, dict)
                    assert health.structuredContent["ok"] is True
                    assert health.structuredContent["data"]["version"] == VERSION

                    invalid = await session.call_tool("audit_query", {"limit": "not-an-integer"})
                    error = _structured_error(invalid)
                    assert error["code"] == "INVALID_ARGUMENT"
                    assert error["message"] == "Invalid tool arguments"
                    assert isinstance(error["request_id"], str) and error["request_id"]
                    assert error["fields"][0]["field"] == "limit"
                    assert "pydantic.dev" not in json.dumps(error)

                    # Exercise every remaining public Tool through the wheel
                    # entry point. This isolated environment intentionally has
                    # no project/device/job, so stable domain errors are the
                    # expected result for target-dependent tools.
                    minimal_calls = {
                        "hcl_get_topology": {"project_id": "missing"},
                        "hcl_get_runtime": {"project_id": "missing"},
                        "h3c_list_devices": {"project_id": "missing"},
                        "h3c_get_facts": {"project_id": "missing", "device_id": 1},
                        "h3c_run_display": {
                            "project_id": "missing",
                            "device_id": 1,
                            "command": "display version",
                        },
                        "h3c_get_config": {"project_id": "missing", "device_id": 1},
                        "h3c_get_interfaces": {"project_id": "missing", "device_id": 1},
                        "h3c_ping": {
                            "project_id": "missing",
                            "device_id": 1,
                            "destination": "192.0.2.1",
                        },
                        "h3c_trace_route": {
                            "project_id": "missing",
                            "device_id": 1,
                            "destination": "192.0.2.1",
                        },
                        "h3c_diff_config": {"project_id": "missing", "device_id": 1},
                        "job_get": {"job_id": "missing"},
                        "job_cancel": {"job_id": "missing"},
                    }
                    for tool_name, arguments in minimal_calls.items():
                        tool_result = await session.call_tool(tool_name, arguments)
                        tool_error = _structured_error(tool_result)
                        assert isinstance(tool_error.get("code"), str), tool_name
                        assert isinstance(tool_error.get("request_id"), str), tool_name

                    audit = await session.call_tool(
                        "audit_query",
                        {"tool": "server_health", "limit": 10},
                    )
                    assert audit.isError is not True
                    assert isinstance(audit.structuredContent, dict)
                    events = audit.structuredContent["data"]["events"]
                    assert events
                    assert all(event["tool"] == "server_health" for event in events)

        stderr.flush()
        stderr.seek(0)
        stderr_text = stderr.read()

    # The human-readable startup banner is captured from stderr.  If it (or
    # any other non-JSON text) were written to stdout, the official client's
    # JSON-RPC reader above would surface a parse exception instead of all four
    # successful protocol exchanges.
    assert f"h3c-hcl-mcp v{VERSION}" in stderr_text
    assert "starting stdio server" in stderr_text


@pytest.mark.parametrize("configuration_source", ["cli", "environment", "json", "yaml"])
async def test_stdio_project_configuration_sources(
    tmp_path: Path,
    configuration_source: str,
) -> None:
    """CLI, environment, JSON, and YAML must work without a default config."""
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "hcl_config_smoke"
    project_dir.mkdir(parents=True)
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "projectInfo": {"name": "Config Smoke", "path": "hcl_config_smoke"},
                "deviceInfoList": [],
            }
        ),
        encoding="utf-8",
    )

    command, argument_prefix, installed, child_cwd = _server_launch(tmp_path)
    env = _isolated_environment(tmp_path, include_source_tree=not installed)
    env.pop("H3C_CLOUD_LAB_PROJECTS", None)
    server_args: list[str] = []

    if configuration_source == "cli":
        server_args = ["--projects-dir", str(projects_dir)]
    elif configuration_source == "environment":
        env["H3C_HCL_MCP__HCL__PROJECTS_DIRS"] = json.dumps([str(projects_dir)])
    elif configuration_source == "json":
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"hcl": {"projects_dirs": [str(projects_dir)]}}),
            encoding="utf-8",
        )
        server_args = ["--config", str(config_path)]
    else:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "hcl:\n  projects_dirs:\n    - " + json.dumps(str(projects_dir)) + "\n",
            encoding="utf-8",
        )
        server_args = ["--config", str(config_path)]

    stderr_path = tmp_path / f"{configuration_source}.stderr.log"
    parameters = StdioServerParameters(
        command=command,
        args=[*argument_prefix, *server_args],
        cwd=child_cwd,
        env=env,
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    with stderr_path.open("w", encoding="utf-8") as stderr:
        async with asyncio.timeout(30):
            async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("hcl_list_projects", {})

    assert result.isError is not True
    assert isinstance(result.structuredContent, dict)
    projects = result.structuredContent["data"]["projects"]
    assert [project["project_id"] for project in projects] == ["hcl_config_smoke"]


@pytest.mark.parametrize("failure_kind", ["missing", "malformed"])
def test_explicit_invalid_config_fails_before_protocol_start(tmp_path: Path, failure_kind: str) -> None:
    """An explicitly selected missing or malformed config must fail closed."""
    command, argument_prefix, installed, child_cwd = _server_launch(tmp_path)
    env = _isolated_environment(tmp_path, include_source_tree=not installed)
    config_path = tmp_path / "selected.yaml"
    if failure_kind == "malformed":
        config_path.write_text("server: [", encoding="utf-8")

    completed = subprocess.run(
        [command, *argument_prefix, "--config", str(config_path)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=child_cwd,
        env=env,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "ERROR:" in completed.stderr
