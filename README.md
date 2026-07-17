# HCL-Lab MCP Server

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.x-green.svg)](https://modelcontextprotocol.io/)

`h3c-hcl-mcp` is a local MCP Server targeting H3C Cloud Lab 5.10.x, with the
current compatibility evidence recorded on HCL 5.10.3. It lets Claude,
Cursor, and other MCP-compatible clients discover HCL projects, inspect
topologies and runtime state, and execute controlled read-only Comware commands
through HCL loopback console ports.

> This is an independent community interoperability project. It is not
> affiliated with or endorsed by H3C. The repository does not distribute HCL
> executables, device images, vendor documentation, or private protocols.

## Current status

Current source version: **v0.1.0-beta.2** (unreleased local beta).

- Real HCL 5.10.3 `project.json` and nested `.net` parsing is implemented.
- Runtime endpoints come only from explicit HCL log bindings and must pass a
  bounded loopback TCP/Telnet + Comware prompt probe.
- `stdio` initialization, `tools/list`, `tools/call`, structured errors, and
  audit correlation are covered with the official MCP Python Client.
- Claude Code 2.1.211 has connected to the Server from an isolated temporary
  profile without modifying the user's real client configuration.
- Claude Desktop and Cursor configuration examples are provided; a recorded
  UI-level smoke test for both clients remains a release-candidate exit check.
- Console command execution is verified end to end with a fake Comware server.
- A successful command against a real HCL device still requires the selected
  project and device to be running in HCL.
- Configuration writes, SSH, NETCONF, and HTTP transport are not part of v0.1.

The package has not been published to PyPI yet. The `uvx h3c-hcl-mcp` command
will become available only after the maintainer approves a public release.

## Requirements

- Windows with a legally installed H3C Cloud Lab 5.10.x (validated on 5.10.3)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Install from source

```powershell
git clone --branch codex/beta2-release-candidate --single-branch https://github.com/FlySun1116/HCL-Lab_mcp.git
cd HCL-Lab_mcp
uv sync
uv run h3c-hcl-mcp --version
```

Until the beta.2 pull request is merged, a plain clone of remote `main` still
selects beta.1. Verify that the last command reports `0.1.0-beta.2`; after the
maintainer merges the candidate, the explicit `--branch` option can be removed.

No configuration file is required. The safe first-run defaults are:

- `stdio` transport
- read-only policy
- `%USERPROFILE%\HCL\Projects` project discovery
- HCL install discovery through explicit configuration, environment variables,
  or the standard Windows uninstall registry metadata
- audit database under `%LOCALAPPDATA%\h3c-hcl-mcp`

To select a project directory explicitly:

```powershell
uv run h3c-hcl-mcp --projects-dir "D:\HCL-Labs\Projects"
```

## MCP client configuration

After `uv sync`, use the generated local executable. Replace `REPO` with the
absolute clone path.

Claude Desktop (`claude_desktop_config.json`) and Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "h3c-hcl": {
      "command": "REPO\\.venv\\Scripts\\h3c-hcl-mcp.exe",
      "args": []
    }
  }
}
```

Optional explicit project root:

```json
{
  "mcpServers": {
    "h3c-hcl": {
      "command": "REPO\\.venv\\Scripts\\h3c-hcl-mcp.exe",
      "args": ["--projects-dir", "C:\\Users\\YOUR_NAME\\HCL\\Projects"]
    }
  }
}
```

## Configuration

Configuration precedence is:

1. CLI arguments
2. `H3C_HCL_MCP__...` environment variables
3. an explicit `--config` file or `H3C_HCL_MCP_CONFIG`
4. the default config location
5. safe model defaults

Default Windows config files are searched in this order:

```text
%LOCALAPPDATA%\h3c-hcl-mcp\config.yaml
%LOCALAPPDATA%\h3c-hcl-mcp\config.yml
%LOCALAPPDATA%\h3c-hcl-mcp\config.json
```

See the [configuration guide](docs/configuration.md),
[config/config.example.yaml](config/config.example.yaml), and
[config/config.example.json](config/config.example.json). Path values support
`~`, `${USERPROFILE}`, and other environment references. Lists supplied by an
environment variable use JSON, for example:

```powershell
$env:H3C_HCL_MCP__HCL__PROJECTS_DIRS='["D:\\HCL-Labs\\Projects"]'
```

An explicitly selected missing or malformed configuration fails before the MCP
protocol starts. With no selected configuration, the server starts safely.

## MCP tools

v0.1 exposes 15 namespaced tools:

| Tool | Status | Purpose |
|---|---|---|
| `server_health` | Ready | Server and optional deep dependency health |
| `hcl_list_projects` | Ready | List local projects without exposing absolute paths |
| `hcl_get_topology` | Ready | Devices, links, and integrity warnings |
| `hcl_get_runtime` | Beta | Project-scoped runtime state and verified endpoints |
| `h3c_list_devices` | Beta | Comware candidates and operability; excludes PC nodes |
| `h3c_get_facts` | Beta | Facts from `display version` |
| `h3c_run_display` | Beta | Policy-controlled display/diagnostic command |
| `h3c_get_config` | Beta | Always-redacted running/startup configuration |
| `h3c_get_interfaces` | Beta | Interface status and structured data |
| `h3c_ping` | Beta | Device-originated ping |
| `h3c_trace_route` | Beta | Device-originated trace route |
| `h3c_diff_config` | Not implemented | Reserved v0.2 contract; returns `NOT_IMPLEMENTED` |
| `job_get` | Reserved | Job lookup for future long-running operations |
| `job_cancel` | Reserved | Job cancellation for future operations |
| `audit_query` | Ready | Query correlated invocation audit events |

Names such as `list_devices`, `execute_command`, `get_device_status`, and
`ping_test` are product-language aliases, not registered MCP tools. Their
canonical mappings are documented in
[docs/TOOL_ALIAS_PROPOSAL.md](docs/TOOL_ALIAS_PROPOSAL.md). `configure_device`
is intentionally unavailable until the v0.2 plan/approval workflow exists.

## Runtime discovery safety

The server does not use HCL private control ports and does not derive a usable
console from `30000 + device_id`.

An endpoint becomes operable only when all of the following are true:

1. an HCL text log binds a project path to a topology alias;
2. a later log event binds that alias and device ID to a Telnet port;
3. no later close event or alias reassignment invalidates the binding;
4. the port is loopback-only and accepts a bounded connection;
5. Telnet negotiation yields a Comware `<...>` or `[...]` prompt.

Login/password prompts are never answered by discovery. The probe sends no CLI
command; at most one empty CRLF is used to request the current prompt.

## Security

- The default policy is read-only.
- Device commands pass an allowlist and injection checks.
- Console connections are restricted to loopback.
- HCL project/runtime metadata and device output are treated as untrusted and
  redacted where applicable at the MCP boundary.
- `redact=false` is rejected in v0.1.
- Public string inputs are bounded before transport and audit processing.
- An enabled audit sink fails closed if an invocation cannot be persisted.
- `server.max_output_chars` bounds device console capture, while
  `server.max_tool_result_bytes` hard-limits every final MCP result in UTF-8 bytes.
- Every invocation records a request ID, outcome, policy result, duration, and
  stable error code when auditing is enabled.
- stdout is reserved for MCP JSON-RPC; logs and startup messages use stderr.

See [SECURITY.md](SECURITY.md) and the [security model](docs/security-model.md).

## Development

```powershell
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --cov=h3c_hcl_mcp --cov-report=term-missing --cov-fail-under=85
uv run python scripts/check_docs.py .
uv run python scripts/check_repository.py .
uv build --clear
uv run python scripts/check_distribution.py dist
```

See [docs/design.md](docs/design.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[GOVERNANCE.md](GOVERNANCE.md), [docs/release-process.md](docs/release-process.md),
[docs/compatibility.md](docs/compatibility.md), and [docs/HANDOVER.md](docs/HANDOVER.md)
for architecture, compatibility, release, and handoff details.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
