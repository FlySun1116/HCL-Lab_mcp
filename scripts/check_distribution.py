"""Validate release archives without extracting untrusted members."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_MAX_MEMBER_BYTES = 10 * 1024 * 1024
_FORBIDDEN_DIRS = {
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}
_FORBIDDEN_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "settings.local.json",
}
_FORBIDDEN_SUFFIXES = {
    ".bin",
    ".chm",
    ".dll",
    ".exe",
    ".img",
    ".iso",
    ".key",
    ".ova",
    ".ovf",
    ".p12",
    ".pdf",
    ".pem",
    ".pfx",
    ".qcow",
    ".qcow2",
    ".vdi",
    ".vmdk",
}
_SDIST_ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CLAUDE.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "LICENSE",
    "NOTICE",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
}
_SDIST_TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".pyi",
    ".rst",
    ".sql",
    ".txt",
    ".yaml",
    ".yml",
}
_SDIST_SPECIAL_NAMES = {"CODEOWNERS"}
_SYNTHETIC_FIXTURE_SUFFIXES = {".cfg", ".json", ".net", ".txt"}
_SDIST_ALLOWED_DIRS = {".github", "config", "docs", "examples", "scripts", "src", "tests"}
_WHEEL_PACKAGE_SUFFIXES = {".py", ".pyi", ".sql"}
_WHEEL_DIST_INFO_NAMES = {"LICENSE", "METADATA", "NOTICE", "RECORD", "WHEEL", "entry_points.txt"}


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    is_link: bool = False
    is_dir: bool = False


def _wheel_members(path: Path) -> list[ArchiveMember]:
    with zipfile.ZipFile(path) as archive:
        return [
            ArchiveMember(item.filename, item.file_size, is_dir=item.is_dir()) for item in archive.infolist()
        ]


def _sdist_members(path: Path) -> list[ArchiveMember]:
    with tarfile.open(path, mode="r:gz") as archive:
        return [
            ArchiveMember(
                item.name,
                item.size,
                is_link=item.issym() or item.islnk(),
                is_dir=item.isdir(),
            )
            for item in archive.getmembers()
        ]


def _validate_member(member: ArchiveMember) -> None:
    name = member.name
    if not name or "\\" in name:
        raise ValueError(f"unsafe archive member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        raise ValueError(f"unsafe archive member path: {name}")
    lowered_parts = {part.casefold() for part in path.parts}
    if lowered_parts & _FORBIDDEN_DIRS:
        raise ValueError(f"local tool state included in archive: {name}")
    if path.name.casefold() in _FORBIDDEN_NAMES:
        raise ValueError(f"sensitive local file included in archive: {name}")
    if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
        raise ValueError(f"forbidden binary or credential file included in archive: {name}")
    if member.is_link:
        raise ValueError(f"archive links are not allowed: {name}")
    if member.size > _MAX_MEMBER_BYTES:
        raise ValueError(f"archive member exceeds {_MAX_MEMBER_BYTES} bytes: {name}")


def _validate_wheel_layout(member: ArchiveMember) -> None:
    path = PurePosixPath(member.name)
    if not path.parts:
        raise ValueError("empty wheel member path")
    top_level = path.parts[0]
    if top_level == "h3c_hcl_mcp":
        if member.is_dir:
            return
        if path.name == "py.typed" or path.suffix.casefold() in _WHEEL_PACKAGE_SUFFIXES:
            return
        raise ValueError(f"wheel package member type is not allowlisted: {member.name}")
    if top_level.startswith("h3c_hcl_mcp-") and top_level.endswith(".dist-info"):
        if member.is_dir:
            return
        if path.name in _WHEEL_DIST_INFO_NAMES:
            return
        raise ValueError(f"wheel metadata member is not allowlisted: {member.name}")
    raise ValueError(f"wheel top-level path is not allowlisted: {member.name}")


def _validate_sdist_layout(member: ArchiveMember) -> None:
    path = PurePosixPath(member.name)
    if not path.parts or not path.parts[0].startswith("h3c_hcl_mcp-"):
        raise ValueError(f"sdist root is not allowlisted: {member.name}")
    if len(path.parts) == 1:
        if member.is_dir:
            return
        raise ValueError(f"sdist member must be below its versioned root: {member.name}")

    relative = PurePosixPath(*path.parts[1:])
    if len(relative.parts) == 1:
        if member.is_dir or relative.name in _SDIST_ROOT_FILES:
            return
        raise ValueError(f"sdist root member is not allowlisted: {member.name}")

    top_level = relative.parts[0]
    if top_level not in _SDIST_ALLOWED_DIRS:
        raise ValueError(f"sdist top-level path is not allowlisted: {member.name}")
    if member.is_dir:
        return

    if len(relative.parts) >= 2 and relative.parts[:2] == ("tests", "fixtures"):
        if relative.suffix.casefold() in _SYNTHETIC_FIXTURE_SUFFIXES:
            return
        raise ValueError(f"synthetic fixture type is not allowlisted: {member.name}")

    if (
        relative.name == "py.typed"
        or relative.name in _SDIST_SPECIAL_NAMES
        or relative.suffix.casefold() in _SDIST_TEXT_SUFFIXES
    ):
        return
    raise ValueError(f"sdist member type is not allowlisted: {member.name}")


def validate_archive(path: Path, members: Iterable[ArchiveMember]) -> int:
    member_list = list(members)
    is_wheel = path.suffix.casefold() == ".whl"
    for member in member_list:
        _validate_member(member)
        if is_wheel:
            _validate_wheel_layout(member)
        else:
            _validate_sdist_layout(member)

    names = [PurePosixPath(member.name).name for member in member_list]
    required = {"LICENSE", "NOTICE", "schema.sql"}
    missing = required.difference(names)
    if missing:
        raise ValueError(f"{path.name} is missing required files: {', '.join(sorted(missing))}")
    return len(member_list)


def check_distribution(dist_dir: Path) -> tuple[int, int]:
    wheels = sorted(dist_dir.glob("h3c_hcl_mcp-*.whl"))
    sdists = sorted(dist_dir.glob("h3c_hcl_mcp-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError(
            f"expected one wheel and one sdist, found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    wheel_count = validate_archive(wheels[0], _wheel_members(wheels[0]))
    sdist_count = validate_archive(sdists[0], _sdist_members(sdists[0]))
    return wheel_count, sdist_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", nargs="?", default="dist", type=Path)
    args = parser.parse_args()

    wheel_count, sdist_count = check_distribution(args.dist_dir)
    print(f"distribution policy passed: wheel={wheel_count} members, sdist={sdist_count} members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
