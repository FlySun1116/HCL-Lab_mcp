"""Validate repository documentation, examples, and workflow references."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

_MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_PINNED_ACTION = re.compile(r"^[^\s@]+@(?P<sha>[0-9a-f]{40})$")
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "app://")


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _markdown_files(root: Path) -> list[Path]:
    top_level = [path for path in root.glob("*.md") if path.is_file()]
    docs = list((root / "docs").rglob("*.md")) if (root / "docs").is_dir() else []
    agents_dir = root / ".claude" / "agents"
    agents = list(agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    return sorted({*top_level, *docs, *agents})


def _validate_markdown_links(root: Path, path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    searchable = _FENCED_BLOCK.sub("", text)
    checked = 0
    for match in _MARKDOWN_LINK.finditer(searchable):
        raw_target = match.group(1).strip().strip("<>")
        if not raw_target or raw_target.startswith("#") or raw_target.startswith(_EXTERNAL_SCHEMES):
            continue
        target = unquote(raw_target.split("#", 1)[0])
        if " " in target:
            target = target.split(" ", 1)[0]
        if not target:
            continue
        candidate = (
            (root / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
        ).resolve()
        if not _inside(root, candidate):
            raise ValueError(
                f"documentation link escapes repository: {path.relative_to(root)} -> {raw_target}"
            )
        if not candidate.exists():
            raise ValueError(f"broken documentation link: {path.relative_to(root)} -> {raw_target}")
        checked += 1
    if text.count("```") % 2:
        raise ValueError(f"unbalanced fenced code block: {path.relative_to(root)}")
    return checked


def _walk_uses(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                found.append(child)
            found.extend(_walk_uses(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_uses(child))
    return found


def _validate_yaml(path: Path, *, require_pinned_actions: bool = False) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML document must be a mapping: {path}")
    if require_pinned_actions:
        for action in _walk_uses(data):
            if action.startswith("./"):
                continue
            if not _PINNED_ACTION.fullmatch(action):
                raise ValueError(f"GitHub Action is not pinned to a full commit SHA: {path}: {action}")


def check_docs(root: Path) -> tuple[int, int, int]:
    root = root.resolve()
    markdown_files = _markdown_files(root)
    link_count = sum(_validate_markdown_links(root, path) for path in markdown_files)

    structured_count = 0
    for path in sorted((root / "config").glob("*.json")) + sorted((root / "examples").glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
        structured_count += 1
    for path in sorted((root / "config").glob("*.yaml")) + sorted((root / "config").glob("*.yml")):
        _validate_yaml(path)
        structured_count += 1

    workflow_count = 0
    for path in sorted((root / ".github" / "workflows").glob("*.yml")):
        _validate_yaml(path, require_pinned_actions=True)
        workflow_count += 1
    return len(markdown_files), link_count, structured_count + workflow_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args()
    markdown_count, link_count, structured_count = check_docs(args.root)
    print(
        "documentation policy passed: "
        f"markdown={markdown_count}, internal_links={link_count}, structured={structured_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
