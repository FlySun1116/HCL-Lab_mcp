from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_distribution import ArchiveMember, validate_archive


def _sdist_members(*extra: ArchiveMember) -> list[ArchiveMember]:
    root = "h3c_hcl_mcp-0.1.0b2"
    return [
        ArchiveMember(root, 0, is_dir=True),
        ArchiveMember(f"{root}/LICENSE", 1),
        ArchiveMember(f"{root}/NOTICE", 1),
        ArchiveMember(f"{root}/src/h3c_hcl_mcp/infrastructure/audit/schema.sql", 1),
        *extra,
    ]


def _wheel_members(*extra: ArchiveMember) -> list[ArchiveMember]:
    dist_info = "h3c_hcl_mcp-0.1.0b2.dist-info"
    return [
        ArchiveMember(f"{dist_info}/licenses/LICENSE", 1),
        ArchiveMember(f"{dist_info}/licenses/NOTICE", 1),
        ArchiveMember("h3c_hcl_mcp/infrastructure/audit/schema.sql", 1),
        ArchiveMember(f"{dist_info}/METADATA", 1),
        ArchiveMember(f"{dist_info}/WHEEL", 1),
        ArchiveMember(f"{dist_info}/RECORD", 1),
        *extra,
    ]


def test_distribution_allowlist_accepts_expected_source_and_fixture_members() -> None:
    root = "h3c_hcl_mcp-0.1.0b2"
    members = _sdist_members(
        ArchiveMember(f"{root}/docs/design.md", 1),
        ArchiveMember(f"{root}/src/h3c_hcl_mcp/__init__.py", 1),
        ArchiveMember(f"{root}/tests/fixtures/synthetic_projects/lab/lab.net", 1),
        ArchiveMember(f"{root}/tests/fixtures/synthetic_projects/lab/DeviceConfig/R1.cfg", 1),
    )

    assert validate_archive(Path("h3c_hcl_mcp-0.1.0b2.tar.gz"), members) == len(members)


def test_distribution_allowlist_accepts_expected_wheel_members() -> None:
    members = _wheel_members(ArchiveMember("h3c_hcl_mcp/mcp/server.py", 1))

    assert validate_archive(Path("h3c_hcl_mcp-0.1.0b2-py3-none-any.whl"), members) == len(members)


@pytest.mark.parametrize(
    "relative_name",
    [
        "vendor/HCL-help.chm",
        "vendor/HCL-manual.pdf",
        "images/device.qcow2",
        "images/device.iso",
        "assets/vendor-logo.png",
        "docs/vendor-logo.png",
        "tests/vendor-lab.net",
    ],
)
def test_distribution_allowlist_rejects_proprietary_or_unexpected_members(
    relative_name: str,
) -> None:
    root = "h3c_hcl_mcp-0.1.0b2"

    with pytest.raises(ValueError, match="allowlisted|forbidden"):
        validate_archive(
            Path("h3c_hcl_mcp-0.1.0b2.tar.gz"),
            _sdist_members(ArchiveMember(f"{root}/{relative_name}", 1)),
        )


def test_distribution_allowlist_rejects_wheel_top_level_injection() -> None:
    with pytest.raises(ValueError, match="top-level path"):
        validate_archive(
            Path("h3c_hcl_mcp-0.1.0b2-py3-none-any.whl"),
            _wheel_members(ArchiveMember("vendor/manual.txt", 1)),
        )


def test_distribution_allowlist_rejects_links_and_oversized_members() -> None:
    root = "h3c_hcl_mcp-0.1.0b2"
    with pytest.raises(ValueError, match="links are not allowed"):
        validate_archive(
            Path("h3c_hcl_mcp-0.1.0b2.tar.gz"),
            _sdist_members(ArchiveMember(f"{root}/docs/link.md", 1, is_link=True)),
        )
    with pytest.raises(ValueError, match="exceeds"):
        validate_archive(
            Path("h3c_hcl_mcp-0.1.0b2.tar.gz"),
            _sdist_members(ArchiveMember(f"{root}/docs/large.md", 10 * 1024 * 1024 + 1)),
        )
