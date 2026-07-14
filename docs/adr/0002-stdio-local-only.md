# ADR-0002: Default stdio Transport, Local-Only HCL Access

**Status**: Accepted  
**Date**: 2026-07-15  
**Deciders**: FlySun1116

## Context

MCP supports two transport mechanisms: stdio (for local processes launched by the client) and Streamable HTTP (for remote/multi-client services). We need to decide the default and when to introduce HTTP.

HCL runs on the user's local Windows machine. The console telnet ports are bound to loopback only. Remote access would require SSH to configured management IPs on devices.

## Decision

**Default to stdio transport. Do not expose HCL through a remote connector in v0.x.**

- v0.1: stdio only. MCP Server is launched by Claude Desktop, Cursor, or other clients as a child process.
- v0.5+: Streamable HTTP with OAuth 2.1, TLS, and Origin validation — for controlled multi-client or remote scenarios.
- HCL loopback console access is inherently local; we will not build a proxy that exposes it remotely.

## Alternatives Considered

| Alternative | Rejected Because |
|---|---|
| HTTP as default | Security risk for local-only HCL console; unnecessary complexity for v0.1 |
| Both transports from v0.1 | Increases attack surface before security model is mature |
| WebSocket transport | Not yet standardized in MCP spec |

## Consequences

- **Positive**: Simplest security model. MCP client handles process lifecycle. No network exposure.
- **Negative**: Cannot share one server across multiple MCP clients. Requires per-client process.
- **Risk**: Future HTTP mode must not accidentally expose loopback console. Mitigated by strict binding and auth requirements.
