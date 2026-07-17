"""Focused tests for the Git-tracked repository release policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_repository import (
    RepositoryPolicyError,
    TrackedFile,
    check_repository,
    parse_git_ls_files,
    validate_tracked_files,
)


def test_parse_git_ls_files_requires_nul_delimited_inventory() -> None:
    assert parse_git_ls_files(b"README.md\x00docs/design.md\x00") == [
        "README.md",
        "docs/design.md",
    ]
    assert parse_git_ls_files(b"") == []

    with pytest.raises(RepositoryPolicyError, match="non-NUL-terminated"):
        parse_git_ls_files(b"README.md\n")
    with pytest.raises(RepositoryPolicyError, match="empty tracked path"):
        parse_git_ls_files(b"README.md\x00\x00")


def test_safe_source_and_small_synthetic_fixtures_are_allowed() -> None:
    files = [
        TrackedFile("README.md", 1_024),
        TrackedFile("src/h3c_hcl_mcp/server.py", 4_096),
        TrackedFile("config/config.example.json", 512),
        TrackedFile("tests/fixtures/device_outputs/display_version.txt", 2_048),
        TrackedFile("tests/fixtures/synthetic_projects/lab/project.json", 256),
        TrackedFile("tests/fixtures/synthetic_projects/lab/topology.net", 512),
        TrackedFile("tests/fixtures/synthetic_projects/lab/DeviceConfig/device.cfg", 512),
    ]

    assert validate_tracked_files(files) == len(files)


@pytest.mark.parametrize(
    "path",
    [
        "vendor/HCL.exe",
        "vendor/HCL.dll",
        "images/device.qcow2",
        "images/device.vmdk",
        "docs/HCL-help.chm",
        "docs/HCL-manual.pdf",
        "archives/support.zip",
        "captures/session.pcapng",
        "logs/HCL.log",
        "assets/vendor-logo.png",
        "assets/vendor-icon.svg",
        "credentials/private.pem",
    ],
)
def test_forbidden_release_asset_types_are_rejected(path: str) -> None:
    with pytest.raises(RepositoryPolicyError, match="forbidden binary or asset type"):
        validate_tracked_files([TrackedFile(path, 64)])


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        ".pypirc",
        "config/credentials.json",
        "config/secrets.yaml",
        "config/token.txt",
        "keys/id_rsa",
        ".claude/settings.local.json",
    ],
)
def test_secret_and_local_state_names_are_rejected(path: str) -> None:
    with pytest.raises(RepositoryPolicyError, match="secret-bearing|local tool state"):
        validate_tracked_files([TrackedFile(path, 64)])


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.example.json",
        ".claude/agents/team-lead.md",
        ".claude/agents/security-reviewer.md",
    ],
)
def test_reviewed_claude_agent_templates_are_allowed(path: str) -> None:
    validate_tracked_files([TrackedFile(path, 64)])


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.json",
        ".claude/agents/unreviewed.md",
        ".claude/hooks/pre-release.ps1",
    ],
)
def test_unreviewed_claude_state_is_rejected(path: str) -> None:
    with pytest.raises(RepositoryPolicyError, match="Agent state"):
        validate_tracked_files([TrackedFile(path, 64)])


def test_hcl_project_data_is_allowed_only_as_small_synthetic_fixture() -> None:
    with pytest.raises(RepositoryPolicyError, match="only under tests/fixtures"):
        validate_tracked_files([TrackedFile("examples/real-lab.net", 100)])

    with pytest.raises(RepositoryPolicyError, match="synthetic fixture type"):
        validate_tracked_files([TrackedFile("tests/fixtures/vendor/device.py", 100)])

    with pytest.raises(RepositoryPolicyError, match="synthetic fixture exceeds"):
        validate_tracked_files(
            [TrackedFile("tests/fixtures/synthetic_projects/lab/device.cfg", 101)],
            max_file_bytes=1_000,
            max_fixture_bytes=100,
        )


def test_general_tracked_file_size_is_bounded() -> None:
    with pytest.raises(RepositoryPolicyError, match="exceeds 100 bytes"):
        validate_tracked_files(
            [TrackedFile("docs/design.md", 101)],
            max_file_bytes=100,
            max_fixture_bytes=50,
        )


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "/absolute.txt",
        "C:/absolute.txt",
        "docs\\windows-path.txt",
        "safe/../../outside.txt",
        "line\nbreak.txt",
    ],
)
def test_unsafe_paths_are_rejected_without_log_injection(path: str) -> None:
    with pytest.raises(RepositoryPolicyError) as exc_info:
        validate_tracked_files([TrackedFile(path, 1)])

    message = str(exc_info.value)
    assert "G:\\Project\\HCL-Lab_mcp" not in message
    assert "\n" not in message


def test_links_non_regular_files_and_case_collisions_are_rejected() -> None:
    with pytest.raises(RepositoryPolicyError, match="links and reparse"):
        validate_tracked_files([TrackedFile("docs/design.md", 1, is_link=True)])
    with pytest.raises(RepositoryPolicyError, match="not a regular file"):
        validate_tracked_files([TrackedFile("docs", 0, is_regular_file=False)])
    with pytest.raises(RepositoryPolicyError, match="duplicate tracked path"):
        validate_tracked_files([TrackedFile("README.md", 1), TrackedFile("readme.md", 1)])


def test_check_repository_uses_only_injected_git_inventory(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("safe", encoding="utf-8")
    # This forbidden file exists in the working tree but is deliberately not
    # present in the injected git ls-files inventory.
    (tmp_path / "untracked.exe").write_bytes(b"MZ")

    count = check_repository(
        tmp_path,
        git_lister=lambda _root: b"README.md\x00",
        max_file_bytes=100,
        max_fixture_bytes=50,
    )

    assert count == 1


def test_resolution_failure_does_not_expose_repository_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(RepositoryPolicyError) as exc_info:
        check_repository(tmp_path, git_lister=lambda _root: b"missing.txt\x00")

    message = str(exc_info.value)
    assert str(tmp_path) not in message
    assert "missing.txt" in message


def test_invalid_size_limit_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="fixture <= global"):
        validate_tracked_files([], max_file_bytes=100, max_fixture_bytes=101)
