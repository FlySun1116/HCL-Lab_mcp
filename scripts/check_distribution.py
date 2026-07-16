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
    ".dll",
    ".exe",
    ".key",
    ".ova",
    ".ovf",
    ".p12",
    ".pem",
    ".pfx",
    ".vdi",
    ".vmdk",
}


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    is_link: bool = False


def _wheel_members(path: Path) -> list[ArchiveMember]:
    with zipfile.ZipFile(path) as archive:
        return [ArchiveMember(item.filename, item.file_size) for item in archive.infolist()]


def _sdist_members(path: Path) -> list[ArchiveMember]:
    with tarfile.open(path, mode="r:gz") as archive:
        return [
            ArchiveMember(item.name, item.size, item.issym() or item.islnk()) for item in archive.getmembers()
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


def validate_archive(path: Path, members: Iterable[ArchiveMember]) -> int:
    member_list = list(members)
    for member in member_list:
        _validate_member(member)

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
