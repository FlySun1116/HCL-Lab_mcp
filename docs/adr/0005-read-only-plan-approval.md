# ADR-0005: Default Read-Only, Plan/Approval for Writes

**Status**: Accepted | **Date**: 2026-07-15 | **Deciders**: FlySun1116

## Context

AI may generate dangerous network commands. Server must enforce safety.

## Decision

Default read-only. Four risk tiers (R0–R3). Write flow: `plan → diff → approval → apply → verify`. Plan TTL 300s; baseline hash change invalidates plan.

## Consequences

Strong security and audit. Human-in-loop for writes — acceptable for v0.x lab use.
