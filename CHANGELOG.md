# Changelog

All notable changes to h3c-hcl-mcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.1] — 2026-07-15

### Fixed — Bugfix from TEST_REPORT_v0.1.md

**P0 Blockers:**
- BUG-001: Unified version to `0.1.0-beta.1` across pyproject.toml, __init__.py, server.py, health.py, __main__.py via single `version.py` source
- BUG-002: Real HCL 5.10.3 project.json format now supported (`projectInfo`/`deviceInfoList` schema) via `_normalize_project_json()`
- BUG-003: Basic HCL process detection (`_is_hcl_running()`) with SimwareClient/SimwareMultiCC process inspection

**P1 Important:**
- BUG-004: Implemented `--config` CLI argument with argparse; unknown args rejected with exit code 2
- BUG-005: Tool name migration map documented in README (5 alias names → canonical namespaced names)
- BUG-006: Removed 4 v0.2 placeholder tools from registration; `h3c_diff_config` returns NOT_IMPLEMENTED error
- BUG-007: Fixed ErrorCode references (3 sites in h3c_read.py now use `ErrorCode.DEVICE_NOT_RUNNING`, etc.)
- BUG-008: Business errors now raise `ToolError` → MCP `isError=true` with structured JSON error payload
- BUG-009: Audit middleware (`audit_middleware.py`) wraps all 15 tools; success/error/internal paths recorded
- BUG-010: `serverInfo.version` set via `mcp._mcp_server.version`; single source in `version.py`

**P2 Minor:**
- BUG-011: README dev instructions updated (`uv sync --extra dev`)
- BUG-012: Ruff lint/format clean (1 E501 fixed, 3 files reformatted)
- BUG-013: Em dash replaced with ASCII `--` in stderr startup messages

### Changed
- Version: `0.0.1` → `0.1.0-beta.1`
- MCP tools: 19 → 15 (4 v0.2 placeholder tools hidden)
- Error mapping: returns → raises `ToolError` (MCP `isError=true`)
- v0.2 change tools removed from `tools/list`

## [0.0.1] — 2026-07-15

### Added — v0.0.1 (Repository Bootstrap)

**Project Governance**
- CLAUDE.md — project rules for all Claude sessions
- docs/design.md — comprehensive architecture design (1121 lines)
- README.md — project overview and quick start
- LICENSE (Apache-2.0), NOTICE, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md
- ADR-0001 through ADR-0006 documenting key architecture decisions
- HANDOVER.md — agent continuity document

**Engineering Skeleton**
- pyproject.toml — Python 3.12+, MCP SDK >=1.28,<2, Pydantic v2
- Six-layer module structure (domain, ports, application, mcp, adapters, infrastructure)
- Minimal `__main__.py` entry point
- CI workflow (lint, typecheck, unit, security)
- Dependabot and CODEOWNERS configuration

**Domain & Contracts (T1)**
- 7 domain modules: errors (31 stable error codes), project, device, command, result, change, audit
- 9 port protocols: ProjectRepository, RuntimeDiscovery, DeviceTransport, CommandParser, PolicyEngine, ApprovalProvider, AuditSink, JobStore, SecretProvider
- 53 contract tests

**MCP Protocol Layer (T2)**
- FastMCP server with Composition Root (`mcp/server.py`)
- 19 MCP tools registered: 15 read-only + 4 v0.2 placeholders
- Error mapping with stable error codes (PROJECT_NOT_FOUND, DEVICE_NOT_FOUND, etc.)
- Shell/command injection detection (37+ patterns)

**HCL Adapter (T3)**
- .net topology file parser using configparser (safe, no eval)
- project.json project metadata parser
- HCL log observer for console port discovery
- Runtime discovery with config/synthetic data
- 5 synthetic test projects (sample, damaged, corrupted, mismatched, empty)
- 74 unit tests

**Comware Driver (T4)**
- ConsoleTelnetTransport with IAC filtering
- Comware CLI prompt state machine (6 prompt modes)
- FactsParser: `display version` output parser
- InterfaceBriefParser: `display interface brief` output parser
- Device capability matrix (9 H3C models)
- Fake telnet server for integration testing
- 81 unit tests

**Security Layer (T5)**
- Policy engine with read-only default mode
- Command allowlist (19 display + 2 diagnostic)
- Command injection detection (37 attack patterns)
- SQLite audit store with WAL mode
- Sensitive data redaction (14 patterns)
- HMAC-signed single-use approval tokens
- Multi-source secret provider
- Multi-source configuration loading
- 121 unit tests

**Integration**
- DeviceSessionManager bridging session-per-device with request-per-request
- Composition Root wiring 8/9 ports with real adapters
- 20 MCP tool integration tests
- uv.lock for reproducible installs

**Quality Gates**
- Ruff lint: 0 errors
- Ruff format: clean
- mypy --strict: 0 errors in 64 source files
- pytest: 349 tests passed
- wheel + sdist build verified
