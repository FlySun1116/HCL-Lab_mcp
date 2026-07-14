"""Tests for HCL .net topology file parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from h3c_hcl_mcp.adapters.hcl.net_parser import (
    NetDeviceEntry,
    NetLinkEntry,
    _validate_path,
    parse_net_file,
    parse_net_topology,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode


class TestValidatePath:
    """Test path validation / traversal rejection."""

    def test_simple_filename_passes(self):
        _validate_path("test.net")

    def test_normalized_path_passes(self):
        _validate_path("subdir/test.net")

    def test_parent_directory_traversal_rejected(self):
        with pytest.raises(DomainError) as exc:
            _validate_path("../etc/passwd")
        assert exc.value.code == ErrorCode.PROJECT_PATH_TRAVERSAL

    def test_absolute_path_allowed(self):
        # Absolute paths are expected — callers pass full file paths.
        # Only path traversal (..) patterns are rejected.
        _validate_path("C:\\Windows\\System32\\test.net")

    def test_double_dot_in_path_rejected(self):
        with pytest.raises(DomainError) as exc:
            _validate_path("project/../../etc/test.net")
        assert exc.value.code == ErrorCode.PROJECT_PATH_TRAVERSAL


class TestParseNetFile:
    """Test parsing of valid .net files."""

    def test_parse_valid_net_file(self, sample_lab_dir: Path):
        net_path = str(sample_lab_dir / "sample_lab.net")
        devices, links = parse_net_file(net_path)

        assert len(devices) == 2
        assert devices[0].name == "S6850_1"
        assert devices[0].device_id == 1
        assert devices[0].device_type == "switch"
        assert devices[0].model == "S6850-56HF"
        assert devices[0].x == 300
        assert devices[0].y == 200

        assert devices[1].name == "MSR36_1"
        assert devices[1].device_id == 2
        assert devices[1].device_type == "router"
        assert devices[1].model == "MSR36-20"

        assert len(links) == 1
        assert links[0].local_device == 1
        assert links[0].local_if == "GigabitEthernet1/0/1"
        assert links[0].remote_device == 2
        assert links[0].remote_if == "GigabitEthernet0/0"

    def test_parse_net_file_to_domain_link(self, sample_lab_dir: Path):
        net_path = str(sample_lab_dir / "sample_lab.net")
        _devices, links = parse_net_file(net_path)

        domain_link = links[0].to_domain_link()
        assert domain_link.local_device_id == 1
        assert domain_link.local_interface == "GigabitEthernet1/0/1"
        assert domain_link.remote_device_id == 2
        assert domain_link.remote_interface == "GigabitEthernet0/0"
        assert domain_link.link_type == "ethernet"

    def test_parse_nonexistent_file_raises(self, tmp_path: Path):
        bad_path = str(tmp_path / "nonexistent.net")
        with pytest.raises(DomainError) as exc:
            parse_net_file(bad_path)
        assert exc.value.code == ErrorCode.PROJECT_DAMAGED

    def test_parse_corrupt_net_file_raises(self, corrupt_net_lab_dir: Path):
        net_path = str(corrupt_net_lab_dir / "corrupt_net_lab.net")
        with pytest.raises(DomainError) as exc:
            parse_net_file(net_path)
        assert exc.value.code == ErrorCode.PROJECT_DAMAGED


class TestParseNetTopology:
    """Test the convenience parse_net_topology function."""

    def test_returns_structured_dict(self, sample_lab_dir: Path):
        net_path = str(sample_lab_dir / "sample_lab.net")
        result = parse_net_topology(net_path)

        assert "device_count" in result
        assert "link_count" in result
        assert "devices" in result
        assert "links" in result
        assert len(result["devices"]) == 2
        assert len(result["links"]) == 1

    def test_nonexistent_file(self, tmp_path: Path):
        bad_path = str(tmp_path / "nonexistent.net")
        with pytest.raises(DomainError) as exc:
            parse_net_topology(bad_path)
        assert exc.value.code == ErrorCode.PROJECT_DAMAGED


class TestNetDeviceEntry:
    """Test NetDeviceEntry helper class."""

    def test_construction(self):
        entry = NetDeviceEntry(
            name="TestDev",
            device_id=1,
            device_type="router",
            model="MSR36-20",
            x=100,
            y=200,
        )
        assert entry.name == "TestDev"
        assert entry.device_id == 1
        assert entry.device_type == "router"
        assert entry.model == "MSR36-20"
        assert entry.x == 100
        assert entry.y == 200

    def test_repr(self):
        entry = NetDeviceEntry(name="TestDev", device_id=1)
        assert "TestDev" in repr(entry)
        assert "1" in repr(entry)


class TestNetLinkEntry:
    """Test NetLinkEntry helper class."""

    def test_construction(self):
        entry = NetLinkEntry(
            local_device=1,
            local_if="GE1/0/1",
            local_port=1,
            remote_device=2,
            remote_if="GE0/0",
            remote_port=1,
        )
        assert entry.local_device == 1
        assert entry.local_if == "GE1/0/1"
        assert entry.remote_device == 2
        assert entry.remote_if == "GE0/0"

    def test_repr(self):
        entry = NetLinkEntry(
            local_device=1,
            local_if="GE1/0/1",
            local_port=1,
            remote_device=2,
            remote_if="GE0/0",
            remote_port=1,
        )
        assert "1" in repr(entry)
        assert "2" in repr(entry)
