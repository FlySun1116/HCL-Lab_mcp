# ADR-0001: Python 3.12 with Official MCP Python SDK Stable Line

**Status**: Accepted  
**Date**: 2026-07-15  
**Deciders**: FlySun1116

## Context

The project needs a runtime language and MCP SDK. Key constraints:

- Must run on Windows (primary platform for HCL users)
- Must integrate with the MCP ecosystem
- Must support async I/O for Telnet/SSH device communication
- Must have mature text parsing libraries for Comware CLI output

## Decision

**Use Python 3.12 with the official MCP Python SDK stable line (`mcp>=1.28,<2`).**

- Python 3.12: current stable release with good Windows compatibility, mature async ecosystem, and strong typing support.
- MCP Python SDK v1.x: production stable line as of 2026-07-15. v2 is pre-release and will be evaluated via ADR once stable.
- Pydantic v2: for input/output schemas and configuration validation.
- uv: for dependency locking and distribution via `uvx`.

## Alternatives Considered

| Alternative | Rejected Because |
|---|---|
| Python 3.8 (HCL bundled) | End-of-life; cannot mix with HCL's bundled runtime |
| TypeScript/Node.js | HCL users may not have Node.js; Python is more common in network engineering |
| Go | Slower iteration for MCP protocol experimentation |
| MCP SDK v2 (pre-release) | API still unstable; will re-evaluate post-stable |
| Rust | Overkill for initial versions; Python faster to iterate on MCP integration |

## Consequences

- **Positive**: Rich async ecosystem (asyncio, telnetlib3, asyncssh). Pydantic provides strong schema validation. uv enables zero-install distribution.
- **Negative**: Python GIL may limit high-concurrency scenarios (mitigated by per-device locking). Startup time slower than compiled languages.
- **Risk**: MCP SDK v1→v2 migration may require changes. Mitigated by locking `<2` and planning ADR-based upgrade evaluation.
