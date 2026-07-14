"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Path to the synthetic test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_lab_dir(fixtures_dir: Path) -> Path:
    """Path to the hcl_sample_001 synthetic project."""
    return fixtures_dir / "synthetic_projects" / "hcl_sample_001"


@pytest.fixture(scope="session")
def damaged_lab_dir(fixtures_dir: Path) -> Path:
    """Path to the hcl_damaged_001 synthetic project (corrupt project.json)."""
    return fixtures_dir / "synthetic_projects" / "hcl_damaged_001"


@pytest.fixture(scope="session")
def mismatch_lab_dir(fixtures_dir: Path) -> Path:
    """Path to the hcl_mismatch_001 synthetic project (project.json vs .net mismatch)."""
    return fixtures_dir / "synthetic_projects" / "hcl_mismatch_001"


@pytest.fixture(scope="session")
def corrupt_net_lab_dir(fixtures_dir: Path) -> Path:
    """Path to the hcl_corrupt_001 synthetic project (invalid .net values)."""
    return fixtures_dir / "synthetic_projects" / "hcl_corrupt_001"


@pytest.fixture(scope="session")
def empty_lab_dir(fixtures_dir: Path) -> Path:
    """Path to a directory with no project.json."""
    return fixtures_dir / "synthetic_projects" / "empty_lab"


@pytest.fixture(scope="session")
def synthetic_projects_dir(fixtures_dir: Path) -> Path:
    """Path to the root synthetic_projects directory."""
    return fixtures_dir / "synthetic_projects"
