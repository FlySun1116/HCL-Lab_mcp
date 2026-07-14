# Contributing to HCL-Lab MCP Server

Thank you for your interest in contributing! This document covers how to set up your environment, make changes, and submit them for review.

## Code of Conduct

This project follows a Code of Conduct. By participating, you agree to uphold it.

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Git

### Setup

```bash
git clone https://github.com/FlySun1116/HCL-Lab_mcp.git
cd HCL-Lab_mcp
uv pip install -e ".[dev]"
```

### Quality Checks

Run these before submitting:

```bash
# Lint
ruff check src/ tests/

# Format
ruff format --check src/ tests/

# Type check
mypy src/

# Tests
pytest

# Build verification
uv build
```

## Development Workflow

1. **Find or create an Issue** — all changes should track to an Issue
2. **Create a feature branch**: `feat/<issue>-<slug>`, `fix/<issue>-<slug>`, `docs/<issue>-<slug>`
3. **Write tests first** — contract tests and unit tests before implementation
4. **Implement** — minimal change to satisfy tests and acceptance criteria
5. **Update docs** — ADR, CHANGELOG, README as applicable
6. **Pass all checks** — lint, typecheck, unit, contract, integration
7. **Create a Draft PR** — get early feedback
8. **Request review** — at least one reviewer required

## Commit Convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(hcl): parse HCL project topology
fix(comware): recover prompt after timeout
test(mcp): add tool schema contract snapshots
docs(adr): record console discovery boundary
chore(repo): update dependencies
```

## Architecture Rules

The code follows **Hexagonal Architecture**. Before contributing, read:

- `CLAUDE.md` — project rules for all contributors
- `docs/design.md` — full architecture, module boundaries, and port interfaces
- `docs/adr/` — architecture decision records

Key rules:

1. **Dependency direction**: `mcp → application → ports ← adapters/infrastructure`, with `domain` at the center
2. **Cross-module**: only pass `domain` strongly-typed objects, never raw dicts or third-party objects
3. **Application layer**: must not import concrete adapters
4. **MCP tools**: must not directly read files, connect Telnet/SSH, or access databases
5. **Adapters**: must convert third-party exceptions to stable domain errors
6. **New adapters**: must not change existing MCP Tool schemas
7. **Public contract changes**: require an ADR and contract tests

## Test Requirements

- **Unit tests**: for domain logic, parsers, and isolated components
- **Contract tests**: for MCP Tool JSON schemas, Port interfaces, and error codes
- **Integration tests**: for adapter wiring and application services
- **Synthetic fixtures only**: tests must use self-constructed HCL project files and device outputs; never commit real topologies, device configs, or credentials

## Security Constraints

- Never commit real device configurations, passwords, tokens, keys, or logs
- Never commit HCL executables, DLLs, disk images, or vendor documentation
- All device output in tests must be synthetic
- Path traversal, command injection, and privilege escalation test cases are mandatory
- See `SECURITY.md` for the full policy

## Review Process

1. Author creates PR with linked Issue
2. CI must pass all required checks
3. At least one reviewer from CODEOWNERS approves
4. High-risk changes also need security reviewer approval
5. Author must not review/merge their own PR
6. Squash merge with conventional commit message

## Definition of Done

- [ ] Implementation complete
- [ ] Unit tests pass (with coverage)
- [ ] Contract tests updated if schemas changed
- [ ] Type checking passes (strict)
- [ ] Linting passes
- [ ] Documentation updated (ADR, CHANGELOG, README)
- [ ] No sensitive data in diff
- [ ] All CI checks green
- [ ] Reviewed by non-author

## Questions?

Open a GitHub Issue with the `question` label or start a Discussion.
