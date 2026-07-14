# Security Policy

## Default Security Posture

The HCL-Lab MCP Server operates under a **default-deny, read-only-first** security model. No tool can modify device configuration unless explicitly enabled by the administrator.

## Risk Levels

| Level | Examples | Default Policy |
|---|---|---|
| **R0** | Project/topology/cache reads | Allowed |
| **R1** | `display`, `ping`, `tracert` | Allowed, rate-limited, audited |
| **R2** | Interface state, candidate config apply | Denied by default; requires role + one-time approval |
| **R3** | Save/restore config, reboot, bulk changes | Denied by default; requires dual confirmation |

## Key Controls

- **Read-only mode** is the default; enforced server-side, not reliant on MCP client UI.
- **Command whitelist**: `h3c_run_display` uses strict prefix validation; newlines, semicolons, pipes, redirects, and control characters are rejected.
- **Write operations**: require short-lived `plan_id` + single-use `approval_token`, bound to caller, target, operation hash, and expiry.
- **Device output**: all text from devices is treated as untrusted external data; never used to construct new commands or interpreted as server instructions.
- **Path safety**: all file paths are resolved and validated to stay within allowed directories; path traversal and symlink escapes are rejected.
- **Loopback only**: HCL console connections are restricted to `127.0.0.1`; no LAN scanning.
- **No HCL private ports**: internal HCL services (TCP 16500, 16600, 18600, etc.) are never accessed or proxied.
- **Secrets**: passwords are sourced only from environment variables, system credential stores, or external secret providers; never logged or stored in plaintext.
- **HTTP mode**: when enabled, binds only to `127.0.0.1` or controlled management network with OAuth 2.1, TLS, Origin/Host validation, and rate limiting.

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

All tool invocations are auditable via the configured audit sink. Audit events include caller, tool, target, policy result, change summary, request ID, and timestamp. See `docs/design.md` for the audit event schema.
