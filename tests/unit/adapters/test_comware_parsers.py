"""Unit tests for Comware CLI output parsers.

Tests FactsParser (display version) and InterfaceBriefParser (display interface brief)
against synthetic fixture outputs.
"""

from __future__ import annotations

import pathlib

import pytest

from h3c_hcl_mcp.adapters.comware.parsers.facts import FactsParser
from h3c_hcl_mcp.adapters.comware.parsers.interfaces import InterfaceBriefParser

FIXTURES_DIR = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "device_outputs"


def _read_fixture(name: str) -> str:
    """Read a fixture file and return its contents."""
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return path.read_text(encoding="utf-8")


# ---- FactsParser Tests ----


class TestFactsParser:
    """Tests for parsing 'display version' output."""

    @pytest.fixture
    def parser(self):
        return FactsParser()

    def test_supports_display_version(self, parser):
        assert parser.supports("", "", "display version") is True
        assert parser.supports("", "", "DISPLAY VERSION") is True
        assert parser.supports("", "", "display interface brief") is False

    def test_parse_s6850_fixture(self, parser):
        raw = _read_fixture("display_version_s6850.txt")
        result = parser.parse(raw)

        assert result["sysname"] == "S6850"
        assert result["comware_version"] == "7.1.070"
        assert result["comware_release"] == "6616"
        assert "2 weeks" in result["uptime"]
        assert result["memory"] == "3G"
        assert result["flash"] == "4M"
        assert result["serial"] == "0203A123456789"
        assert result["last_reboot_reason"] == "User reboot"
        assert result["_raw"] == raw
        assert "_parse_error" not in result

    def test_parse_msr36_fixture(self, parser):
        raw = _read_fixture("display_version_msr36.txt")
        result = parser.parse(raw)

        assert result["sysname"] == "MSR36-20"
        assert result["comware_version"] == "7.1.064"
        assert result["comware_release"] == "0821P20"
        assert "1 week" in result["uptime"]
        assert result["memory"] == "2G"
        assert result["flash"] == "256M"
        assert result["serial"] == "0203B987654321"
        assert result["last_reboot_reason"] == "Power on"
        assert result["_raw"] == raw

    def test_parse_model_from_output(self, parser):
        raw = _read_fixture("display_version_s6850.txt")
        result = parser.parse(raw)
        assert result["model"] == "S6850"

    def test_parse_missing_fields(self, parser):
        """Parser should handle partial output gracefully."""
        raw = "MyRouter uptime is 5 days, 1 hour"
        result = parser.parse(raw)

        assert result["sysname"] == "MyRouter"
        assert result["uptime"] == "5 days, 1 hour"
        assert result["_raw"] == raw
        # Other fields simply won't be present
        assert "comware_version" not in result

    def test_parse_empty_output(self, parser):
        result = parser.parse("")
        assert result["_raw"] == ""
        assert "_parse_error" not in result

    def test_parse_garbage(self, parser):
        result = parser.parse("!@#$%^&*() garbage data")
        assert result["_raw"] == "!@#$%^&*() garbage data"
        assert "_parse_error" not in result  # Should handle gracefully

    def test_parse_preserves_raw(self, parser):
        raw = _read_fixture("display_version_s6850.txt")
        result = parser.parse(raw)
        assert result["_raw"] is raw  # Same object reference
        assert result["_raw"] == raw


# ---- InterfaceBriefParser Tests ----


class TestInterfaceBriefParser:
    """Tests for parsing 'display interface brief' output."""

    @pytest.fixture
    def parser(self):
        return InterfaceBriefParser()

    def test_supports_interface_brief(self, parser):
        assert parser.supports("", "", "display interface brief") is True
        assert parser.supports("", "", "DISPLAY INTERFACE BRIEF") is True
        assert parser.supports("", "", "display version") is False

    def test_parse_all_interfaces(self, parser):
        raw = _read_fixture("display_interface_brief.txt")
        result = parser.parse(raw)

        assert "interfaces" in result
        ifaces = result["interfaces"]
        assert len(ifaces) == 8

        # Verify first interface
        ge1 = ifaces[0]
        assert ge1["name"] == "GE1/0/1"
        assert ge1["status"] == "UP"
        assert ge1["speed"] == "1G"
        assert ge1["description"] == "Uplink to Core"

    def test_parse_up_interfaces(self, parser):
        raw = _read_fixture("display_interface_brief.txt")
        result = parser.parse(raw)
        up = [i for i in result["interfaces"] if i["status"] == "UP"]
        # GE1/0/1 UP, GE1/0/2 UP, GE1/0/4 UP, XGE1/0/1 UP, LoopBack0 UP = 5
        assert len(up) == 5

    def test_parse_down_interfaces(self, parser):
        raw = _read_fixture("display_interface_brief.txt")
        result = parser.parse(raw)
        down = [i for i in result["interfaces"] if i["status"] == "DOWN"]
        assert len(down) >= 2  # GE1/0/3 DOWN, XGE1/0/2 DOWN, LoopBack1 DOWN

    def test_parse_loopback(self, parser):
        raw = _read_fixture("display_interface_brief.txt")
        result = parser.parse(raw)
        loopbacks = [i for i in result["interfaces"] if i["name"].startswith("LoopBack")]
        assert len(loopbacks) == 2
        lo0 = loopbacks[0]
        assert lo0["name"] == "LoopBack0"
        assert lo0["speed"] == "-"

    def test_parse_preserves_raw(self, parser):
        raw = _read_fixture("display_interface_brief.txt")
        result = parser.parse(raw)
        assert result["_raw"] == raw

    def test_parse_empty(self, parser):
        result = parser.parse("")
        assert "_parse_error" in result
        assert result["interfaces"] == []

    def test_parse_no_table(self, parser):
        result = parser.parse("some random output without a table header")
        assert "_parse_error" in result
        assert result["interfaces"] == []
