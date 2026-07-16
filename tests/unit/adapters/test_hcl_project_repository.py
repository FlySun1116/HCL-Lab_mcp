"""Tests for HCL project repository adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from h3c_hcl_mcp.adapters.hcl.project_repository import (
    HCLProjectRepository,
    _find_net_file,
    _get_file_mtime,
    _read_project_json,
    _validate_project_path,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import LabProject, Topology


class TestValidateProjectPath:
    """Test project path validation."""

    def test_simple_path_passes(self):
        _validate_project_path("my_lab")

    def test_traversal_rejected(self):
        with pytest.raises(DomainError) as exc:
            _validate_project_path("../etc")
        assert exc.value.code == ErrorCode.PROJECT_PATH_TRAVERSAL


class TestReadProjectJson:
    """Test reading project.json files."""

    def test_read_valid_project_json(self, sample_lab_dir: Path):
        data = _read_project_json(str(sample_lab_dir))
        assert data["name"] == "Sample Lab"
        assert data["id"] == "hcl_sample_001"
        assert data["version"] == "5.10.3"
        assert len(data["devices"]) == 2

    def test_read_damaged_project_json_raises(self, damaged_lab_dir: Path):
        with pytest.raises(DomainError) as exc:
            _read_project_json(str(damaged_lab_dir))
        assert exc.value.code == ErrorCode.PROJECT_DAMAGED

    def test_read_missing_project_json_raises(self, tmp_path: Path):
        with pytest.raises(DomainError) as exc:
            _read_project_json(str(tmp_path))
        assert exc.value.code == ErrorCode.PROJECT_NOT_FOUND


class TestFindNetFile:
    """Test finding .net topology files."""

    def test_finds_net_file(self, sample_lab_dir: Path):
        result = _find_net_file(str(sample_lab_dir))
        assert result is not None
        assert result.endswith(".net")

    def test_no_net_file_returns_none(self, empty_lab_dir: Path):
        result = _find_net_file(str(empty_lab_dir))
        assert result is None

    def test_traversal_rejected(self):
        with pytest.raises(DomainError) as exc:
            _find_net_file("../etc")
        assert exc.value.code == ErrorCode.PROJECT_PATH_TRAVERSAL


class TestGetFileMtime:
    """Test file modification time helper."""

    def test_returns_datetime(self, sample_lab_dir: Path):
        json_path = str(sample_lab_dir / "project.json")
        result = _get_file_mtime(json_path)
        assert result is not None

    def test_nonexistent_file_returns_none(self, tmp_path: Path):
        result = _get_file_mtime(str(tmp_path / "nonexistent.json"))
        assert result is None


class TestHCLProjectRepository:
    """Integration tests for HCLProjectRepository."""

    @pytest.fixture
    def repo(self, synthetic_projects_dir: Path) -> HCLProjectRepository:
        return HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])

    @pytest.mark.asyncio
    async def test_list_projects_returns_all_valid_projects(self, repo: HCLProjectRepository):
        projects, cursor = await repo.list_projects()
        # Valid projects: sample_lab, mismatch_lab, corrupt_net_lab
        # damaged_lab has invalid JSON, empty_lab has no project.json
        project_ids = {p.project_id for p in projects}
        assert "hcl_sample_001" in project_ids
        assert "hcl_mismatch_001" in project_ids
        assert "hcl_corrupt_001" in project_ids
        assert cursor is None

    @pytest.mark.asyncio
    async def test_list_projects_with_query_filter(self, repo: HCLProjectRepository):
        projects, _ = await repo.list_projects(query="Sample")
        assert len(projects) == 1
        assert projects[0].project_id == "hcl_sample_001"

    @pytest.mark.asyncio
    async def test_list_projects_with_limit(self, repo: HCLProjectRepository):
        projects, cursor = await repo.list_projects(limit=2)
        assert len(projects) <= 2
        # With 3 projects, cursor should not be None if limit < total
        if len(projects) == 2:
            assert cursor is not None

    @pytest.mark.asyncio
    async def test_get_project_found(self, repo: HCLProjectRepository):
        project = await repo.get_project("hcl_sample_001")
        assert isinstance(project, LabProject)
        assert project.project_id == "hcl_sample_001"
        assert project.name == "Sample Lab"
        assert project.hcl_version == "5.10.3"
        assert project.device_count == 2

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, repo: HCLProjectRepository):
        with pytest.raises(DomainError) as exc:
            await repo.get_project("nonexistent_project")
        assert exc.value.code == ErrorCode.PROJECT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_project_damaged(self, synthetic_projects_dir: Path):
        # hcl_damaged_001 has corrupt JSON — list_projects skips it,
        # but direct get should fail
        repo = HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])
        with pytest.raises(DomainError) as exc:
            await repo.get_project("hcl_damaged_001")
        assert exc.value.code in (ErrorCode.PROJECT_NOT_FOUND, ErrorCode.PROJECT_DAMAGED)

    @pytest.mark.asyncio
    async def test_get_topology_full(self, repo: HCLProjectRepository):
        topo = await repo.get_topology("hcl_sample_001")
        assert isinstance(topo, Topology)
        assert topo.project_id == "hcl_sample_001"
        assert len(topo.devices) == 2
        assert len(topo.links) == 1

        # Check devices
        s6850 = topo.get_device_by_name("S6850_1")
        assert s6850 is not None
        assert s6850.model == "S6850-56HF"
        assert s6850.category == "switch"

        msr36 = topo.get_device_by_name("MSR36_1")
        assert msr36 is not None
        assert msr36.category == "router"

        # Check link
        link = topo.links[0]
        assert link.local_device_id == 1
        assert link.remote_device_id == 2

    @pytest.mark.asyncio
    async def test_get_topology_mismatch_produces_warnings(self, repo: HCLProjectRepository):
        topo = await repo.get_topology("hcl_mismatch_001")
        # mismatch_lab: project.json has 1 device, .net has 2 devices
        assert len(topo.warnings) > 0
        warning_text = " ".join(topo.warnings).lower()
        assert "mismatch" in warning_text or "not in" in warning_text or ".net" in warning_text

    @pytest.mark.asyncio
    async def test_get_topology_not_found(self, repo: HCLProjectRepository):
        with pytest.raises(DomainError) as exc:
            await repo.get_topology("nonexistent_project")
        assert exc.value.code == ErrorCode.PROJECT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_topology_missing_net_file(self, synthetic_projects_dir: Path):
        # Create a project dir without a .net file

        no_net_dir = synthetic_projects_dir / "no_net_lab"
        no_net_dir.mkdir(exist_ok=True)
        json_path = no_net_dir / "project.json"
        json_path.write_text(
            '{"name": "No Net Lab", "id": "no_net_lab", "version": "5.10.3", "devices": []}',
            encoding="utf-8",
        )

        try:
            repo = HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])
            topo = await repo.get_topology("no_net_lab")
            assert len(topo.devices) == 0
            assert len(topo.links) == 0
            assert len(topo.warnings) > 0
            warnings_lower = " ".join(topo.warnings).lower()
            assert "no" in warnings_lower or ".net" in warnings_lower
        finally:
            json_path.unlink(missing_ok=True)
            no_net_dir.rmdir()

    @pytest.mark.asyncio
    async def test_add_projects_dir(self, repo: HCLProjectRepository, tmp_path: Path):
        repo.add_projects_dir(str(tmp_path))
        assert str(tmp_path) in repo.projects_dirs

    @pytest.mark.asyncio
    async def test_add_projects_dir_duplicate(self, repo: HCLProjectRepository, synthetic_projects_dir: Path):
        before = len(repo.projects_dirs)
        repo.add_projects_dir(str(synthetic_projects_dir))
        assert len(repo.projects_dirs) == before

    @pytest.mark.asyncio
    async def test_add_projects_dir_traversal_rejected(self, repo: HCLProjectRepository):
        with pytest.raises(DomainError) as exc:
            repo.add_projects_dir("../etc")
        assert exc.value.code == ErrorCode.PROJECT_PATH_TRAVERSAL

    @pytest.mark.asyncio
    async def test_topology_helper_methods(self, repo: HCLProjectRepository):
        topo = await repo.get_topology("hcl_sample_001")

        # get_device
        dev = topo.get_device(1)
        assert dev is not None
        assert dev.name == "S6850_1"

        # get_device not found
        assert topo.get_device(999) is None

        # get_device_by_name
        dev = topo.get_device_by_name("MSR36_1")
        assert dev is not None
        assert dev.device_id == 2

        # get_device_by_name not found
        assert topo.get_device_by_name("Nonexistent") is None

        # get_links_for_device
        links = topo.get_links_for_device(1)
        assert len(links) == 1
        assert links[0].local_device_id == 1

        # get_links_for_device with no links
        links = topo.get_links_for_device(999)
        assert len(links) == 0

        # to_dict
        d = topo.to_dict()
        assert d["project_id"] == "hcl_sample_001"
        assert len(d["devices"]) == 2
        assert len(d["links"]) == 1


class TestHCLRealFormat5103:
    """BUG-002: Verify that real HCL 5.10.3 project.json format is parsed correctly."""

    def test_list_real_format_project(self, synthetic_projects_dir):
        """project.json with projectInfo/deviceInfoList should be discoverable."""
        repo = HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])
        projects, _ = asyncio.run(repo.list_projects())
        # Find the real format project
        real_project = None
        for p in projects:
            if p.project_id == "hcl_real_5103":
                real_project = p
                break
        assert real_project is not None, "hcl_real_5103 project not found in list"
        assert real_project.name == "Test Lab 5103"
        assert real_project.device_count == 2
        # Real HCL 5.10.3 projectInfo has no hclVersion field
        assert real_project.device_count == 2

    def test_get_topology_real_format(self, synthetic_projects_dir):
        """Topology should include devices from deviceInfoList."""
        repo = HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])
        topo = asyncio.run(repo.get_topology("hcl_real_5103"))
        assert topo.project_id == "hcl_real_5103"
        assert len(topo.devices) == 2
        device_names = {d.name for d in topo.devices}
        assert "S6850_1" in device_names
        assert "MSR36_1" in device_names
        assert len(topo.links) == 1

    def test_device_fields_real_format(self, synthetic_projects_dir):
        """Device fields should be correctly mapped from real format."""
        repo = HCLProjectRepository(projects_dirs=[str(synthetic_projects_dir)])
        topo = asyncio.run(repo.get_topology("hcl_real_5103"))
        s6850 = topo.get_device_by_name("S6850_1")
        assert s6850 is not None
        assert s6850.model == "S6850-56HF"
        assert s6850.category == "switch"
        assert s6850.comware_version == "7.1.070"
