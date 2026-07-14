# HCL-Lab MCP Server

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.x-green.svg)](https://modelcontextprotocol.io/)

**h3c-hcl-mcp** is an open-source MCP (Model Context Protocol) Server that enables AI agents — including Claude Desktop, Claude Code, Cursor, ChatGPT MCP Client, Cline, Roo Code, and other MCP-compatible clients — to interact with local [H3C Cloud Lab (HCL)](https://www.h3c.com/cn/Products_And_Solution/Cloud_Computing/HCL/) network simulation environments.

> ⚠️ **Important**: This project is a community interoperability tool. It is **not** affiliated with, endorsed by, or sponsored by H3C. You must legally install HCL yourself; this repository does not contain, distribute, or download any HCL executables, images, or documentation.

## What It Does

- **Discover** HCL projects, devices, and links on your local machine
- **Connect** to running H3C/Comware devices through HCL loopback Telnet console or SSH
- **Execute** controlled Comware CLI commands (`display`, diagnostics)
- **Retrieve** device facts, interfaces, configurations, and topology data
- **Analyze** lab topologies and assist with network experiments
- (Future) **Provision** configuration changes with plan → diff → approval → apply workflow

## Quick Start

### Prerequisites

- Windows with [H3C Cloud Lab 5.10.x](https://www.h3c.com/cn/Products_And_Solution/Cloud_Computing/HCL/) installed
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
# Via uvx (recommended — no explicit install needed)
uvx h3c-hcl-mcp

# Or via pip
pip install h3c-hcl-mcp
h3c-hcl-mcp
```

### MCP Client Configuration

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "h3c-hcl": {
      "command": "uvx",
      "args": [
        "--from", "h3c-hcl-mcp==0.1.0",
        "h3c-hcl-mcp",
        "--config", "C:\\Users\\YOUR_NAME\\.config\\h3c-hcl-mcp\\config.yaml"
      ]
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "h3c-hcl": {
      "command": "uvx",
      "args": [
        "--from", "h3c-hcl-mcp==0.1.0",
        "h3c-hcl-mcp",
        "--config", "C:\\Users\\YOUR_NAME\\.config\\h3c-hcl-mcp\\config.yaml"
      ]
    }
  }
}
```

## Current Status

| Version | Stage | Description |
|---|---|---|
| `v0.0.1` | Bootstrap | Repository governance, package skeleton, CI, ADR |
| `v0.1.0` | Planned | Read-only MVP — HCL project discovery, console Telnet, device facts |
| `v1.0.0` | Target | Stable API, full test coverage, multi-client verified |

**Current version: v0.0.1 (pre-alpha)** — development has just started. See [docs/design.md](docs/design.md) for the full architecture.

## Architecture

```
Any MCP Client (Claude, Cursor, ChatGPT, …)
        │
   MCP Protocol (stdio / Streamable HTTP)
        │
   HCL-Lab MCP Server
        │
   ┌────┴────┐
   │         │
HCL Layer  Comware Layer
   │         │
Topology   CLI over
Discovery  Telnet/SSH
```

The codebase follows **Hexagonal Architecture** with strict dependency direction:

```text
mcp → application → ports ← adapters/infrastructure
                    domain
```

See [docs/design.md](docs/design.md) for module boundaries, port interfaces, and tool schemas.

## MCP Tools (v0.1)

| Tool | Status | Description |
|---|---|---|
| `server_health` | ✅ Ready | Server version, config status, health checks |
| `hcl_list_projects` | ✅ Ready | List local HCL projects |
| `hcl_get_topology` | ✅ Ready | Devices, interfaces, links |
| `hcl_get_runtime` | ✅ Ready | HCL process status, device runtime, console availability |
| `h3c_list_devices` | ✅ Ready | Operable devices with transport capabilities |
| `h3c_get_facts` | ✅ Ready | sysname, Comware version, uptime, model |
| `h3c_run_display` | ✅ Ready | Execute whitelisted `display` commands |
| `h3c_get_config` | ✅ Ready | Running/startup/snapshot config (redacted) |
| `h3c_get_interfaces` | Interface status, speed, description, addresses |
| `h3c_ping` | Network reachability test |
| `h3c_trace_route` | Path tracing |
| `h3c_diff_config` | Config diff without writing to device |

## Security

- **Default: read-only**. Write operations require explicit opt-in, plan approval, and audit.
- All device output is treated as **untrusted data**.
- Passwords are never logged or stored in plaintext.
- Commands go through whitelist validation — no shell injection, no `eval`.
- Only connects to `127.0.0.1` for HCL console; no LAN scanning.

See [SECURITY.md](SECURITY.md) for the full security model.

## Development

```bash
# Clone
git clone https://github.com/FlySun1116/HCL-Lab_mcp.git
cd HCL-Lab_mcp

# Create venv and install dev dependencies
uv sync --extra dev

# Lint & typecheck
uv run ruff check .
uv run ruff format --check .
uv run mypy src/

# Run tests
uv run pytest

# Build
uv build

# Run MCP Inspector
npx @modelcontextprotocol/inspector uv run h3c-hcl-mcp
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.

## Disclaimer

This is a community interoperability project. H3C, HCL, Comware, and related trademarks are the property of their respective owners. Users must comply with HCL's license terms and install HCL legally. This repository does not include, redistribute, or reverse-engineer any HCL proprietary software.
