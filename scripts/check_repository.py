"""Reject unsafe tracked files before they can enter a public release.

The repository inventory comes exclusively from ``git ls-files -z``.  The
validation core operates on injected metadata so its policy can be tested
without invoking Git or following filesystem links.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_MAX_TRACKED_FILE_BYTES = 2 * 1024 * 1024
_MAX_SYNTHETIC_FIXTURE_BYTES = 256 * 1024

_FORBIDDEN_DIRS = {
    ".agents",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}

_ALLOWED_CLAUDE_FILES = {
    ".claude/agents/comware-driver-engineer.md",
    ".claude/agents/contract-architect.md",
    ".claude/agents/hcl-adapter-engineer.md",
    ".claude/agents/mcp-api-engineer.md",
    ".claude/agents/qa-release-engineer.md",
    ".claude/agents/security-reviewer.md",
    ".claude/agents/team-lead.md",
    ".claude/settings.example.json",
}

_FORBIDDEN_SUFFIXES = {
    # Native executables and opaque binaries.
    ".appx",
    ".bin",
    ".com",
    ".dll",
    ".dylib",
    ".exe",
    ".jar",
    ".msi",
    ".msix",
    ".scr",
    ".so",
    ".sys",
    # HCL/device images and virtual disks.
    ".img",
    ".iso",
    ".ova",
    ".ovf",
    ".qcow",
    ".qcow2",
    ".vdi",
    ".vhd",
    ".vhdx",
    ".vmdk",
    # Vendor help/document bundles and archives.
    ".7z",
    ".bz2",
    ".chm",
    ".gz",
    ".hlp",
    ".pdf",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
    # Captures, dumps, and raw logs.
    ".cap",
    ".core",
    ".dmp",
    ".dump",
    ".etl",
    ".evtx",
    ".log",
    ".pcap",
    ".pcapng",
    # Common copied vendor artwork.
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
    # Credential containers and private keys.
    ".der",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
}

_SECRET_EXACT_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "settings.local.json",
    "token.json",
    "tokens.json",
}
_SECRET_DATA_STEMS = {"credential", "credentials", "secret", "secrets", "token", "tokens"}
_SECRET_DATA_SUFFIXES = {".ini", ".json", ".toml", ".txt", ".yaml", ".yml"}

_FIXTURE_ROOT = ("tests", "fixtures")
_SYNTHETIC_FIXTURE_SUFFIXES = {".cfg", ".json", ".net", ".txt"}
_PROJECT_DATA_SUFFIXES = {".cfg", ".net"}


class RepositoryPolicyError(ValueError):
    """A tracked repository member violates the public-release policy."""


@dataclass(frozen=True)
class TrackedFile:
    """Filesystem-independent metadata for one tracked path."""

    path: str
    size: int
    is_link: bool = False
    is_regular_file: bool = True


GitLister = Callable[[Path], bytes]


def _display_path(path: str) -> str:
    """Return a single-line escaped relative path safe for diagnostics."""

    return json.dumps(path, ensure_ascii=True)


def _validated_relative_path(raw_path: str) -> PurePosixPath:
    if (
        not raw_path
        or "\\" in raw_path
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw_path)
    ):
        raise RepositoryPolicyError(f"unsafe tracked path: {_display_path(raw_path)}")

    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or (path.parts and ":" in path.parts[0])
    ):
        raise RepositoryPolicyError(f"unsafe tracked path: {_display_path(raw_path)}")
    return path


def parse_git_ls_files(payload: bytes) -> list[str]:
    """Parse the exact NUL-delimited output of ``git ls-files -z``."""

    if not payload:
        return []
    if not payload.endswith(b"\x00"):
        raise RepositoryPolicyError("git ls-files returned a non-NUL-terminated inventory")

    encoded_paths = payload[:-1].split(b"\x00")
    if any(not item for item in encoded_paths):
        raise RepositoryPolicyError("git ls-files returned an empty tracked path")
    return [os.fsdecode(item) for item in encoded_paths]


def _is_fixture(path: PurePosixPath) -> bool:
    return len(path.parts) >= 3 and path.parts[:2] == _FIXTURE_ROOT


def _validate_file_policy(
    tracked: TrackedFile,
    *,
    max_file_bytes: int,
    max_fixture_bytes: int,
) -> None:
    path = _validated_relative_path(tracked.path)
    display = _display_path(tracked.path)

    if tracked.is_link:
        raise RepositoryPolicyError(f"tracked links and reparse points are not allowed: {display}")
    if not tracked.is_regular_file:
        raise RepositoryPolicyError(f"tracked path is not a regular file: {display}")
    if tracked.size < 0:
        raise RepositoryPolicyError(f"tracked file has an invalid size: {display}")

    lowered_parts = {part.casefold() for part in path.parts}
    normalized = path.as_posix().casefold()
    if ".claude" in lowered_parts and normalized not in _ALLOWED_CLAUDE_FILES:
        raise RepositoryPolicyError(
            f"local tool state or unreviewed Agent state must not be tracked: {display}"
        )
    if lowered_parts & _FORBIDDEN_DIRS:
        raise RepositoryPolicyError(f"local tool state must not be tracked: {display}")

    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if (
        name in _SECRET_EXACT_NAMES
        or name.startswith(".env.")
        or (path.stem.casefold() in _SECRET_DATA_STEMS and suffix in _SECRET_DATA_SUFFIXES)
    ):
        raise RepositoryPolicyError(f"secret-bearing filename must not be tracked: {display}")
    if suffix in _FORBIDDEN_SUFFIXES:
        raise RepositoryPolicyError(f"forbidden binary or asset type must not be tracked: {display}")

    fixture = _is_fixture(path)
    if fixture:
        if suffix not in _SYNTHETIC_FIXTURE_SUFFIXES:
            raise RepositoryPolicyError(f"synthetic fixture type is not allowlisted: {display}")
        if tracked.size > max_fixture_bytes:
            raise RepositoryPolicyError(f"synthetic fixture exceeds {max_fixture_bytes} bytes: {display}")
    elif suffix in _PROJECT_DATA_SUFFIXES:
        raise RepositoryPolicyError(
            f"HCL-shaped project data is allowed only under tests/fixtures: {display}"
        )

    if tracked.size > max_file_bytes:
        raise RepositoryPolicyError(f"tracked file exceeds {max_file_bytes} bytes: {display}")


def validate_tracked_files(
    tracked_files: Iterable[TrackedFile],
    *,
    max_file_bytes: int = _MAX_TRACKED_FILE_BYTES,
    max_fixture_bytes: int = _MAX_SYNTHETIC_FIXTURE_BYTES,
) -> int:
    """Pure validation core for injected tracked-file metadata."""

    if max_file_bytes <= 0 or max_fixture_bytes <= 0 or max_fixture_bytes > max_file_bytes:
        raise ValueError("repository size limits must be positive and fixture <= global")

    count = 0
    seen: set[str] = set()
    for tracked in tracked_files:
        identity = tracked.path.casefold()
        if identity in seen:
            raise RepositoryPolicyError(f"duplicate tracked path: {_display_path(tracked.path)}")
        seen.add(identity)
        _validate_file_policy(
            tracked,
            max_file_bytes=max_file_bytes,
            max_fixture_bytes=max_fixture_bytes,
        )
        count += 1
    return count


def _run_git_ls_files(repository_root: Path) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RepositoryPolicyError("unable to obtain the tracked-file inventory from Git") from error
    return completed.stdout


def _is_link_or_reparse(path: Path, status: os.stat_result) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    attributes = int(getattr(status, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return bool(reparse_flag and attributes & reparse_flag)


def collect_tracked_files(
    repository_root: Path,
    *,
    git_lister: GitLister = _run_git_ls_files,
) -> list[TrackedFile]:
    """Collect safe metadata for only the paths reported by Git."""

    root = repository_root.resolve(strict=True)
    raw_paths = parse_git_ls_files(git_lister(root))
    tracked_files: list[TrackedFile] = []

    for raw_path in raw_paths:
        relative = _validated_relative_path(raw_path)
        candidate = root.joinpath(*relative.parts)
        display = _display_path(raw_path)

        try:
            current = root
            link_found = False
            for part in relative.parts:
                current = current / part
                status = current.lstat()
                if _is_link_or_reparse(current, status):
                    link_found = True
                    break

            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            status = candidate.lstat()
        except (OSError, RuntimeError, ValueError) as error:
            raise RepositoryPolicyError(f"tracked path cannot be safely resolved: {display}") from error

        tracked_files.append(
            TrackedFile(
                path=raw_path,
                size=status.st_size,
                is_link=link_found or _is_link_or_reparse(candidate, status),
                is_regular_file=stat.S_ISREG(status.st_mode),
            )
        )

    return tracked_files


def check_repository(
    repository_root: Path,
    *,
    git_lister: GitLister = _run_git_ls_files,
    max_file_bytes: int = _MAX_TRACKED_FILE_BYTES,
    max_fixture_bytes: int = _MAX_SYNTHETIC_FIXTURE_BYTES,
) -> int:
    """Validate the current Git-tracked repository inventory."""

    tracked_files = collect_tracked_files(repository_root, git_lister=git_lister)
    return validate_tracked_files(
        tracked_files,
        max_file_bytes=max_file_bytes,
        max_fixture_bytes=max_fixture_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", nargs="?", default=".", type=Path)
    args = parser.parse_args(argv)

    try:
        count = check_repository(args.repository)
    except RepositoryPolicyError as error:
        parser.exit(1, f"repository policy failed: {error}\n")
    print(f"repository policy passed: {count} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
