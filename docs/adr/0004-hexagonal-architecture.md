# ADR-0004: Hexagonal Architecture

**Status**: Accepted | **Date**: 2026-07-15 | **Deciders**: FlySun1116

## Context

Six module areas must be independently testable and parallel-developed.

## Decision

Hexagonal (Ports & Adapters): `mcp → application → ports ← adapters/infrastructure`, `domain` at center. Cross-module only via domain objects. Only `mcp/server.py` wires adapters.

## Consequences

Positive: testability, swappable adapters, parallel work. Risk: abstraction overhead — mitigated by v0.1 vertical slice.
