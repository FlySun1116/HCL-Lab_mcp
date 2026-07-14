# ADR-0003: HCL Project Files + Loopback Console as v0.x Integration Boundary

**Status**: Accepted  
**Date**: 2026-07-15  
**Deciders**: FlySun1116

## Context

HCL provides several integration surfaces: project files on disk, loopback telnet console ports, named pipes, and internal TCP control services. We must decide which surfaces are permissible for an open-source interoperability layer.

## Decision

**Use HCL user project files (read-only) and loopback telnet console as the v0.x integration boundary.**

Stable, permissible boundaries:
- Read user-created HCL project files (`project.json`, `.net`, `DeviceConfig/`)
- Read-only inspection of HCL processes, logs, and local listening ports
- Connect to HCL loopback telnet console ports that HCL creates for running devices
- Connect via SSH/NETCONF to device management IPs (if configured)

**Do NOT implement or reverse-engineer:**
- HCL internal TCP control services (ports 16500, 16600, 18600, etc.)
- HCL named pipes (`\\.\pipe\topo1-device1`)
- VirtualBox API or VM management
- Private wire protocols from `SimwareClient.exe` or related components

## Alternatives Considered

| Alternative | Rejected Because |
|---|---|
| Direct VirtualBox control | Bypasses HCL state machine; may corrupt projects |
| Internal TCP control ports | Not a public API; license prohibits reverse engineering |
| Named pipe access | Unstable internal mechanism; no documentation |
| Memory/process injection | Illegal and unethical |

## Consequences

- **Positive**: Clean legal boundary. File formats and telnet are well-understood, documented interfaces.
- **Negative**: Cannot automate device start/stop in v0.x. Users must manually start devices in HCL GUI. Mitigated by clear user guidance in `hcl_get_runtime`.
- **Risk**: HCL may change telnet port allocation or project format in future versions. Mitigated by multi-source discovery (config, logs, probing) and version-specific compatibility matrix.
