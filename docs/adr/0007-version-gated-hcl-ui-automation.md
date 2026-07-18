# ADR-0007: Version-gated HCL UI Automation Provider

**Status**: Proposed

**Date**: 2026-07-18
**Deciders**: FlySun1116, project maintainers

## Context

The project goal extends beyond reading an existing lab: an Agent must eventually be able to create an
isolated topology, start devices, configure Comware, and verify the result. HCL 5.10.3 does not expose a
documented public SDK or REST API for project and device lifecycle operations. ADR-0003 and ADR-0006
correctly prohibit reverse-engineering the private TCP services, directly controlling VirtualBox, or editing
project files behind HCL's state machine.

The public [H3C developer API catalog](https://www.h3c.com/cn/Developer/Resource_Tools/API_interface/)
documents APIs for other H3C platforms but does not list an HCL lifecycle API. This is evidence about the
published catalog, not proof that no partner-only interface exists; an official HCL SDK remains preferred if
H3C makes one available.

An inspection of a locally installed HCL 5.10.3 instance found that its Qt client exposes Windows UI
Automation elements with semantic IDs, including:

- `toolButtonNew`, `toolButtonOpen`, `toolButtonSave`, and `toolButtonSaveAs`;
- `toolButtonRouter`, `toolButtonSwitch`, `toolButtonHost`, and `toolButtonLink`;
- `toolButtonStartAll` and `toolButtonStopAll`;
- identifiable modal text and buttons for unsaved-project confirmation.

This surface is materially safer than private-protocol or project-file manipulation because operations still
pass through the HCL client and its normal state machine. It is nevertheless a GUI integration surface, not a
vendor compatibility guarantee.

## Proposed decision

Add an optional, Windows-only `HclControlProvider` backed exclusively by Windows UI Automation patterns.
The provider remains disabled by default and is not part of the v0.1 Tool contract.

The provider must:

1. require an interactive desktop session and an already running, responsive HCL client;
2. require an exact allowlisted HCL version and a successful capability probe of every automation ID needed
   by the requested plan;
3. use semantic Automation IDs and supported UI Automation patterns, never fixed screen coordinates,
   synthetic mouse movement, image matching, private ports, named pipes, or direct project-file writes;
4. operate only on a newly created isolated project or a project explicitly included in an execution grant;
5. refuse to confirm save, overwrite, delete, stop-with-unsaved-config, or other destructive dialogs unless
   the immutable plan explicitly contains that operation and its required approval claim;
6. verify every side effect through both the visible HCL state and the existing read-only project/runtime
   adapters before advancing the transaction journal;
7. stop at the first unexpected window, missing control, changed label, modal dialog, timeout, baseline change,
   or HCL version mismatch;
8. persist intent before the first UI action and use project-scoped leases, idempotency keys, checkpoints, and
   bounded retries;
9. perform a resource preflight before starting devices. Initial defaults should require at least 4 GiB of
   free physical memory, start at most one device concurrently, and reject plans whose model estimate exceeds
   the configured budget;
10. expose no raw UI handle, local path, window title, or HCL-internal identifier to an MCP Client.

The first real-provider milestone is deliberately small:

```text
create isolated project
  -> add at most two allowlisted low-resource devices
  -> connect one link
  -> start devices sequentially
  -> wait for verified loopback console prompts
  -> run read-only acceptance checks
```

Configuration writes remain a separate Comware transaction. Successful topology creation must never imply
permission to enter `system-view`, save startup configuration, or modify another project.

## Public contract impact

This ADR does not itself register MCP Tools. Domain models, Provider Ports, fake adapters, planning, resource
budgets, transaction journaling, and crash-recovery tests may be developed while the ADR is Proposed.

Registering lifecycle or configuration Tools is a separate public-contract decision. It requires reviewed
Tool schemas, error semantics, policy defaults, and an execution-grant design. The existing 15 v0.1 Tools and
their default read-only behavior remain unchanged.

## Alternatives considered

| Alternative | Decision |
|---|---|
| Wait indefinitely for a vendor SDK | Keep as the preferred future provider, but it does not satisfy current local automation goals |
| Reverse-engineer ports 16500/16600/18600 | Rejected by ADR-0003/0006 and by the project security boundary |
| Directly edit `project.json` or `.net` files | Rejected; bypasses HCL validation and can corrupt or confuse project identity |
| Control VirtualBox directly | Rejected; bypasses HCL lifecycle and ownership state |
| Coordinate- or image-based desktop automation | Rejected; resolution, theme, localization, and timing make it unsafe and non-deterministic |
| Require all lifecycle work to be manual | Safe fallback, but it cannot deliver autonomous topology construction |

## Consequences

### Positive

- Provides a legal, observable path toward local HCL lifecycle automation without implementing a private
  protocol.
- Preserves HCL's own state transitions and project generation behavior.
- Can fail closed on unsupported HCL versions and unexpected UI state.
- Fits the existing hexagonal boundary: the application depends on `HclControlProvider`, while UI Automation
  remains an adapter detail.

### Negative

- Windows-only and dependent on an unlocked interactive desktop.
- HCL updates or localization changes can invalidate the capability contract.
- GUI operations are slower and less reliable than a supported SDK.
- CI can fully test only the control kernel and a fake provider; real HCL validation requires a dedicated
  Windows runner with licensed HCL assets that are never uploaded.

## Acceptance criteria

The ADR can move to **Accepted** only after all of the following are demonstrated:

- maintainer approval of the Provider boundary and public safety model;
- a fake-provider saga covering success, retry, cancellation, baseline change, resource rejection, partial
  failure, compensation, and process-restart recovery;
- a version-locked HCL 5.10.3 capability probe that performs no side effects;
- creation of an isolated one-device smoke project without modifying an existing project;
- sequential two-device startup under the memory budget and successful console prompt verification;
- an audit record and transaction journal that allow every UI action to be reconstructed without containing
  local paths or sensitive project data.
