# Governance

## Scope

HCL-Lab_mcp is a community interoperability project. It is not affiliated with H3C and does not distribute or reverse engineer HCL or Comware proprietary components.

## Roles

- **Maintainer**: owns roadmap, repository settings, release authority, security response, and final public-contract decisions.
- **Module owner**: reviews changes within a documented source boundary and its tests.
- **Security reviewer**: independently reviews policy, transport, redaction, audit, dependency, and release changes.
- **Contributor/Agent**: implements a bounded Issue or task card and supplies reproducible evidence; it cannot approve its own change.

Until a maintainer team exists, `FlySun1116` is the repository maintainer. CODEOWNERS should move from an individual account to GitHub Teams when additional maintainers join.

## Decisions

Routine fixes follow GitHub Flow and the existing architecture. Changes to public MCP Tool schemas, Port contracts, stable error codes, licensing, supported transports, or default security policy require an ADR and maintainer approval. Security fixes may be prepared privately before coordinated disclosure.

## Reviews and branches

- `main` is the only release source and must remain protected.
- Feature branches use short-lived `feat/`, `fix/`, `docs/`, or `refactor/` names.
- A high-risk change requires both a module-owner and security review.
- Authors and Agents do not approve or merge their own PRs.
- Force push, unsigned release tags, direct `main` pushes, and bypassing required checks are prohibited.

## Release authority

Only a maintainer may authorize merge to `main`, version promotion, signed tags, GitHub Releases, PyPI Trusted Publishing, MCPB/Registry submission, or changes to repository protection and release environments. The reproducible process is defined in [docs/release-process.md](docs/release-process.md).

## Agent contributions

Agent Teams follow `CLAUDE.md` and [docs/agent-team-playbook.md](docs/agent-team-playbook.md). The Team Lead owns shared files and Git integration; teammates use disjoint file ownership, do not commit or publish, and hand off exact tests and unresolved risks.

## Conduct and security

All participation follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Do not report vulnerabilities in public Issues; use the private process in [SECURITY.md](SECURITY.md).
