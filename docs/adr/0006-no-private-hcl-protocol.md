# ADR-0006: No Unauthorized HCL Private Protocol

**Status**: Accepted | **Date**: 2026-07-15 | **Deciders**: FlySun1116

## Context

HCL has internal TCP services (16500, 16600, 18600). License prohibits reverse engineering.

## Decision

Do not implement or proxy any HCL private protocol. HCL lifecycle tools (`hcl_start_devices` etc.) only after official API/SDK or explicit H3C authorization.

## Consequences

No device start/stop automation in v0.x. Users manage devices via HCL GUI. Core value (CLI, topology, config) unaffected.
