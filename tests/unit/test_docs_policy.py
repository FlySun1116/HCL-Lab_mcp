from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_docs import check_docs


def _minimal_repo(tmp_path: Path, *, action_ref: str = "a" * 40) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "examples").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "README.md").write_text("[Design](docs/design.md)\n", encoding="utf-8")
    (tmp_path / "docs" / "design.md").write_text("# Design\n", encoding="utf-8")
    (tmp_path / "config" / "config.json").write_text('{"safe": true}\n', encoding="utf-8")
    (tmp_path / "config" / "config.yaml").write_text("safe: true\n", encoding="utf-8")
    (tmp_path / "examples" / "client.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        f"name: CI\non: push\njobs:\n  check:\n    steps:\n      - uses: actions/checkout@{action_ref}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_docs_policy_accepts_valid_links_examples_and_pinned_actions(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)

    assert check_docs(root) == (2, 1, 4)


def test_docs_policy_rejects_broken_or_escaping_links(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "README.md").write_text("[Missing](docs/missing.md)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="broken documentation link"):
        check_docs(root)

    (root / "README.md").write_text("[Escape](../outside.md)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes repository"):
        check_docs(root)


def test_docs_policy_rejects_invalid_structured_examples(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "examples" / "client.json").write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        check_docs(root)


def test_docs_policy_rejects_mutable_action_references(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path, action_ref="v7")

    with pytest.raises(ValueError, match="not pinned"):
        check_docs(root)
