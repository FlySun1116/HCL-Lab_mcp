## Outcome

Describe the user-visible result and link the Issue/Task ID.

## Scope and architecture

- Owned modules/files:
- Public Tool/Port/error/security impact:
- ADR/design update, if required:

## Verification

- [ ] Ruff check and format pass.
- [ ] Mypy strict passes.
- [ ] Unit, contract, integration, and relevant Windows tests pass.
- [ ] Active-v0.1 line coverage remains at least 85%.
- [ ] Wheel and sdist build; installed console-entry-point stdio smoke passes.
- [ ] Documentation, CHANGELOG, and HANDOVER match the implementation.

## Safety and release

- [ ] No real credentials, topology/configuration, raw HCL logs, vendor binaries/images/docs, or private protocol implementation is included.
- [ ] No test, assertion, type check, output bound, redaction, or default policy was weakened to make CI pass.
- [ ] Real-device testing was read-only, or an explicitly approved write plan is linked.
- [ ] Push/tag/Release/PyPI and other external actions are clearly listed as executed or not executed.

## Handoff

List exact test results, assumptions, remaining risks, external blockers, and the next owner.
