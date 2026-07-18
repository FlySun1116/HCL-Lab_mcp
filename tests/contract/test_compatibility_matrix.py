"""Contract tests for the machine-readable compatibility evidence matrix."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPOSITORY_ROOT / "config" / "compatibility.yaml"
DOCUMENTATION_PATH = REPOSITORY_ROOT / "docs" / "compatibility.md"

ALLOWED_STATUSES = {"real-pass", "real-negative", "synthetic-pass", "not-tested"}
REQUIRED_ENTRY_FIELDS = {
    "id",
    "hcl_version",
    "device_family",
    "models",
    "capability",
    "transport",
    "status",
    "evidence",
    "limitations",
}


def _load_matrix() -> dict[str, Any]:
    loaded = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def test_compatibility_matrix_schema_and_status_enumeration() -> None:
    matrix = _load_matrix()
    assert matrix.get("schema_version") == 1
    entries = matrix.get("entries")
    assert isinstance(entries, list) and entries

    identifiers: set[str] = set()
    for entry in entries:
        assert isinstance(entry, dict)
        assert set(entry) == REQUIRED_ENTRY_FIELDS
        identifier = entry["id"]
        assert _non_empty_string(identifier)
        assert identifier not in identifiers
        identifiers.add(identifier)

        assert _non_empty_string(entry["hcl_version"])
        assert _non_empty_string(entry["device_family"])
        assert _non_empty_string(entry["capability"])
        assert _non_empty_string(entry["transport"])
        assert entry["status"] in ALLOWED_STATUSES

        models = entry["models"]
        assert isinstance(models, list) and models
        assert all(_non_empty_string(model) for model in models)

        limitations = entry["limitations"]
        assert isinstance(limitations, list) and limitations
        assert all(_non_empty_string(limitation) for limitation in limitations)


def test_every_entry_has_safe_existing_repository_evidence_or_external_explanation() -> None:
    for entry in _load_matrix()["entries"]:
        evidence = entry["evidence"]
        assert isinstance(evidence, dict)
        assert set(evidence) == {"repository_paths", "external"}

        repository_paths = evidence["repository_paths"]
        external = evidence["external"]
        assert isinstance(repository_paths, list)
        assert all(_non_empty_string(path) for path in repository_paths)
        assert external is None or _non_empty_string(external)
        assert repository_paths or _non_empty_string(external)

        for relative_path in repository_paths:
            pure_path = PurePosixPath(relative_path)
            assert not pure_path.is_absolute()
            assert ".." not in pure_path.parts
            assert (REPOSITORY_ROOT / Path(*pure_path.parts)).is_file(), relative_path


def test_real_pass_never_relies_only_on_fixture_evidence() -> None:
    real_pass_entries = [entry for entry in _load_matrix()["entries"] if entry["status"] == "real-pass"]
    assert real_pass_entries, "The matrix must retain at least one evidenced real-pass capability"

    for entry in real_pass_entries:
        evidence = entry["evidence"]
        non_fixture_paths = [
            path for path in evidence["repository_paths"] if not path.startswith("tests/fixtures/")
        ]
        assert non_fixture_paths or _non_empty_string(evidence["external"]), entry["id"]


def test_documentation_covers_every_machine_entry_and_status() -> None:
    documentation = DOCUMENTATION_PATH.read_text(encoding="utf-8")
    matrix = _load_matrix()

    for status in ALLOWED_STATUSES:
        assert f"`{status}`" in documentation
    for entry in matrix["entries"]:
        assert f"`{entry['id']}`" in documentation
