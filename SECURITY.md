# Security Policy

## Default Security Posture

The HCL-Lab MCP Server operates under a **default-deny, read-only-first** security model. v0.1 registers no device-write tool and cannot enable configuration writes through settings.

## Risk Levels

| Level | Examples | Default Policy |
|---|---|---|
| **R0** | Project/topology/cache reads | Allowed |
| **R1** | `display`, `ping`, `tracert` | Allowed, bounded/concurrency-limited, audited when audit is enabled |
| **R2** | Interface state, candidate config apply | Not implemented in v0.1; future versions require role + one-time approval |
| **R3** | Save/restore config, reboot, bulk changes | Not implemented in v0.1; future versions require dual confirmation |

## Key Controls

- **Read-only mode** is the default; enforced server-side, not reliant on MCP client UI.
- **Command whitelist**: `h3c_run_display` uses strict prefix validation; newlines, semicolons, pipes, redirects, and control characters are rejected.
- **Write operations**: are absent in v0.1. The planned v0.2 design requires a short-lived `plan_id` and single-use approval token before any write Tool can be registered.
- **Device output**: all text from devices is treated as untrusted external data; never used to construct new commands or interpreted as server instructions.
- **Path safety**: all file paths are resolved and validated to stay within allowed directories; path traversal and symlink escapes are rejected.
- **Loopback only**: HCL console connections accept loopback hostnames/addresses only; the transport boundary rejects LAN endpoints and non-console transports.
- **No HCL private ports**: internal HCL services (TCP 16500, 16600, 18600, etc.) are never accessed or proxied.
- **Secrets**: v0.1 discovery never answers login/password prompts. Comware credential forms are redacted from device results, logs, and audit data; future authenticated adapters must use environment references, a system credential store, or an external provider.
- **Bounded inputs and sessions**: public strings, concurrent sessions, idle lifetime, and commands per persistent console session have server-side limits.
- **Audit fail-closed**: when auditing is enabled, an invocation whose event cannot be persisted returns a stable internal error instead of an unaudited success.
- **HTTP mode**: is rejected by v0.1. A future HTTP transport must add loopback/controlled-network binding, OAuth 2.1, TLS, Origin/Host validation, and rate limiting before release.

## Reporting a Vulnerability

**Please do NOT file a public GitHub Issue for security vulnerabilities.**

Email the maintainer directly with details. We aim to acknowledge within 48 hours and provide an initial assessment within 5 business days.

### Coordinated Disclosure

1. Reporter sends details privately
2. Maintainer acknowledges within 48 hours
3. Fix developed on a private branch
4. Fix reviewed and tested
5. Release published with advisory
6. Public disclosure after users have upgrade window

## Supported Versions

| Version | Security Updates |
|---|---|
| `v1.0.x` (future) | Yes (stable) |
| `v0.x` (current) | Best effort — API may change |

## Audit

All tool invocations are auditable via the configured audit sink. Audit events include caller, tool, target, policy result, change summary, request ID, and timestamp. Local HCL metadata and device text remain explicitly untrusted content. See `docs/design.md` for the audit event schema.
