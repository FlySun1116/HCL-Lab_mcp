# Changelog

All notable changes to h3c-hcl-mcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta.2] — Unreleased

### Added

- Added HCL 5.10.x ConfigObj-style `.net` fixtures and parser coverage for nested device/link sections.
- Added chronological HCL log reduction for project binding, console creation, console closure, and topology-alias rebinding.
- Added bounded loopback Telnet/Comware prompt verification before a console endpoint can be reported as usable.
- Added `ProjectAwareRuntimeDiscovery` so project topology is registered before both project-wide and single-device discovery.
- Added official MCP `ClientSession` stdio subprocess tests for no-config startup, `initialize`, `tools/list`, `tools/call`, validation, configuration sources, and pre-protocol configuration failures.
- Added Python 3.12 clean-artifact stdio tests through `H3C_HCL_MCP_TEST_EXECUTABLE`; the
  installed console entry point is exercised outside the source tree for both wheel and sdist.
- Added structured Comware ping and traceroute parsers with strict destination/count/hop schemas.
- Added a final `CallToolResult` UTF-8 byte budget and stable `OUTPUT_TOO_LARGE` failures across
  success, validation, timeout, unknown-tool, and error response paths.
- Added an explicit active-v0.1 line-coverage definition and an 85% CI gate.
- Added structured Bug, Feature, and Agent Task Issue forms plus a release-oriented PR checklist so a new Agent Team can receive bounded ownership and verification requirements directly from GitHub.

### Fixed

- Parsed real HCL 5.10.3 `projectInfo`/`deviceInfoList` fields and merged device metadata with `.net` authoritative IDs using case-insensitive names.
- Rejected absolute, traversal, separator-bearing, and root-escaping project IDs, including resolved symlink escapes.
- Removed formula-derived console availability and the previous "any HCL process means every device is running" false positive.
- Kept project-wide and single-device runtime results coherent through a short shared cache; closed or rebound consoles no longer leave stale endpoints.
- Passed verified `project_id`/`device_id` endpoint context into console sessions and isolated per-task session routing to prevent cross-device execution.
- Used the configured connection timeout instead of endpoint confidence as the Telnet timeout.
- Made a missing default configuration safe and optional while keeping explicitly selected missing or malformed files fail-closed.
- Added `PyYAML` as a runtime dependency and corrected nested JSON-list environment-variable coercion.
- Enforced v0.1 `stdio` transport, exclusive per-device concurrency, and valid unique transport preferences during configuration validation.
- Wired `allow_display_prefixes` as a restriction-only subset of the built-in display allowlist and `deny_patterns` as additional case-insensitive literal denials; neither can bypass mandatory injection/dangerous-command checks.
- Normalized official stdio argument validation failures to structured `INVALID_ARGUMENT` results without Pydantic input or documentation URL leakage.
- Normalized unknown Tool calls, added correlated audit events, and enforced `server.max_tool_seconds` at the ToolManager boundary with stable `TIMEOUT` results.
- Correlated response and audit `request_id`, preserved domain error codes, audited schema failures, and separated invocation `outcome` from `policy_result`.
- Normalized audit timestamps to UTC for correct offset-aware filtering and migrated legacy error outcomes.
- Honored `audit.enabled=false` without creating an audit database.
- Removed project absolute paths and device `config_path` values from MCP responses and sanitized path-bearing or device-output-bearing domain errors at the MCP boundary.
- Filtered HCL PC/terminal nodes from H3C device results and applied mandatory sensitive-output redaction at the MCP boundary; `redact=false` now fails with `POLICY_DENIED`.
- Covered complete and truncated PKCS#8/RSA/EC/OpenSSH/encrypted private-key blocks and SNMPv3 credentials in mandatory redaction.
- Closed and invalidated Telnet sessions after prompt failure, EOF, cancellation, truncation, or command timeout so late bytes cannot contaminate a later request.
- Moved project scanning/topology parsing off the stdio event loop and reconciled deleted topology devices from cached runtime state.
- Made deep health checks inspect configured projects and real runtime discovery instead of reporting an unconditional dependency result.
- Moved process inspection and bounded log loading off the stdio event loop, closed SQLite/scandir/Telnet resources explicitly, and limited log observation to 16 files and 4 MiB per file.
- Classified `ping` and `tracert` as diagnostic operations and parsed their summaries instead of returning ambiguous raw-only data.
- Redacted SNMP communities, NTP authentication keys, RADIUS/HWTACACS shared keys, and all supported `super password` role/hash/cipher/simple forms in both full and quick paths.
- Passed `hcl_list_projects` cursors through to the repository so pagination can advance beyond the first page.
- Marked device-derived result content as untrusted and removed duplicate raw parser copies from structured results.

### Changed

- Version metadata now identifies the candidate as `0.1.0-beta.2`.
- The v0.1 public surface remains 15 namespaced tools. Proposed short aliases are not registered; `h3c_diff_config` remains an explicit `NOT_IMPLEMENTED` placeholder.
- Client configuration examples now launch a source-installed local virtual-environment executable. The package has not yet been published to PyPI, so `uvx h3c-hcl-mcp` is not a supported installation path for this candidate.
- Upgraded checkout, setup-uv, upload-artifact, and gitleaks Actions to current Node 24 releases and pinned every third-party Action to a reviewed full commit SHA.

### Verification status

- Frozen-candidate gates pass: Ruff check/format over 101 files, mypy over 69 source files, and **628 pytest tests** on Python 3.14.5 with ResourceWarning/PytestUnraisable failures treated as errors.
- Active-v0.1 line coverage is **86.83%** (3,646 statements, 480 missed), above the 85% hard gate.
- `uv build --clear` produces one `0.1.0b2` wheel and one sdist. Each artifact installs in a separate clean Python 3.12.13 environment, exposes `h3c-hcl-mcp --version`, and passes all **7 official stdio tests** through the installed executable.
- The installed-artifact test asserts the exact 15-Tool set, minimally invokes every public Tool, and performs a non-empty filtered audit query.
- Synthetic parser, fake console, MCP protocol, validation, audit, configuration, redaction, timeout, and concurrency paths are automated.
- A local HCL 5.10.3 project was parsed read-only, but the target project/devices were not running during the latest runtime check. Successful real-device `display version` and `display ip interface brief` remain release-candidate exit checks.
- No tag, GitHub Release, or PyPI publication has been created for this candidate.

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
