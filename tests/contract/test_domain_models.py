"""Contract tests for domain models — verify schemas and immutability."""

import pytest

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.change import ChangePlan
from h3c_hcl_mcp.domain.command import CommandResult, CommandTarget
from h3c_hcl_mcp.domain.device import (
    DeviceRuntime,
    DeviceState,
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import DeviceRef, LabProject, Link, Topology
from h3c_hcl_mcp.domain.result import ToolResult


class TestErrorCodes:
    """Error codes must be stable — changes break MCP clients."""

    def test_error_codes_are_enum(self):
        assert isinstance(ErrorCode.PROJECT_NOT_FOUND, ErrorCode)

    def test_domain_error_has_code(self):
        err = DomainError(ErrorCode.PROJECT_NOT_FOUND, "Project abc not found")
        assert err.code == ErrorCode.PROJECT_NOT_FOUND
        assert err.message == "Project abc not found"

    def test_domain_error_to_dict(self):
        err = DomainError(ErrorCode.COMMAND_DENIED, "Not allowed", {"reason": "read-only"})
        d = err.to_dict()
        assert d["code"] == "COMMAND_DENIED"
        assert d["details"]["reason"] == "read-only"


class TestLabProject:
    def test_create_minimal(self):
        p = LabProject(project_id="proj-1", name="Test Lab", path="C:\\labs\\proj-1")
        assert p.project_id == "proj-1"

    def test_is_immutable(self):
        p = LabProject(project_id="proj-1", name="Test Lab", path="C:\\labs\\proj-1")
        with pytest.raises((TypeError, ValueError)):
            p.name = "Changed"  # type: ignore


class TestDeviceRef:
    def test_create_minimal(self):
        d = DeviceRef(project_id="proj-1", device_id=1, name="S6850_1")
        assert d.device_id == 1

    def test_fully_specified(self):
        d = DeviceRef(
            project_id="proj-1",
            device_id=1,
            name="S6850_1",
            model="S6850",
            comware_version="7.1.070",
            config_path="DeviceConfig\\S6850_1.cfg",
            category="switch",
        )
        assert d.model == "S6850"
        assert d.category == "switch"


class TestTopology:
    def test_get_device_by_id(self):
        d1 = DeviceRef(project_id="p1", device_id=1, name="R1")
        d2 = DeviceRef(project_id="p1", device_id=2, name="R2")
        topo = Topology(project_id="p1", devices=[d1, d2])
        assert topo.get_device(1) == d1
        assert topo.get_device(99) is None

    def test_get_device_by_name(self):
        d1 = DeviceRef(project_id="p1", device_id=1, name="Router-1")
        topo = Topology(project_id="p1", devices=[d1])
        assert topo.get_device_by_name("Router-1") == d1
        assert topo.get_device_by_name("missing") is None

    def test_get_links_for_device(self):
        link = Link(
            local_device_id=1,
            local_interface="GE1/0/1",
            remote_device_id=2,
            remote_interface="GE1/0/1",
        )
        topo = Topology(project_id="p1", links=[link])
        assert len(topo.get_links_for_device(1)) == 1
        assert len(topo.get_links_for_device(2)) == 1
        assert len(topo.get_links_for_device(99)) == 0

    def test_to_dict(self):
        d = DeviceRef(project_id="p1", device_id=1, name="R1")
        topo = Topology(project_id="p1", devices=[d], warnings=["stale config"])
        result = topo.to_dict()
        assert result["project_id"] == "p1"
        assert len(result["warnings"]) == 1


class TestRuntimeEndpoint:
    def test_create(self):
        ep = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            port=30001,
            source=DiscoverySource.FORMULA,
            confidence=0.7,
        )
        assert ep.host == "127.0.0.1"
        assert ep.confidence == 0.7


class TestDeviceRuntime:
    def test_is_running(self):
        rt = DeviceRuntime(device_id=1, device_name="R1", state=DeviceState.RUNNING)
        assert rt.is_running is True

    def test_console_available(self):
        ep = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            port=30001,
            source=DiscoverySource.PROBE,
            confidence=0.9,
        )
        rt = DeviceRuntime(
            device_id=1,
            device_name="R1",
            state=DeviceState.RUNNING,
            endpoints=[ep],
        )
        assert rt.console_available is True

    def test_best_endpoint_preference(self):
        telnet_ep = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            port=30001,
            source=DiscoverySource.PROBE,
            confidence=0.9,
        )
        ssh_ep = RuntimeEndpoint(
            transport=TransportType.SSH,
            port=22,
            source=DiscoverySource.CONFIG,
            confidence=1.0,
        )
        rt = DeviceRuntime(
            device_id=1,
            device_name="R1",
            state=DeviceState.RUNNING,
            endpoints=[telnet_ep, ssh_ep],
        )
        best = rt.best_endpoint(preferred=[TransportType.SSH, TransportType.CONSOLE_TELNET])
        assert best is not None
        assert best.transport == TransportType.SSH


class TestCommandTarget:
    def test_create(self):
        t = CommandTarget(project_id="proj-1", device_id=1, device_name="R1")
        assert t.project_id == "proj-1"

    def test_repr(self):
        t = CommandTarget(project_id="proj-1", device_id=1)
        r = repr(t)
        assert "proj-1" in r
        assert "1" in r


class TestCommandResult:
    def test_defaults(self):
        t = CommandTarget(project_id="p1", device_id=1)
        r = CommandResult(target=t, command="display version")
        assert r.truncated is False
        assert r.content_trust == "untrusted_device_output"


class TestToolResult:
    def test_success(self):
        r = ToolResult.success(
            request_id="req-001",
            data={"status": "ok"},
            target={"project_id": "p1"},
            duration_ms=100.0,
        )
        assert r.ok is True
        assert r.data == {"status": "ok"}
        assert r.changed is False

    def test_failure(self):
        r = ToolResult.failure(
            request_id="req-002",
            code="PROJECT_NOT_FOUND",
            message="Project p99 not found",
        )
        assert r.ok is False
        assert r.data is not None
        assert r.data["error"]["code"] == "PROJECT_NOT_FOUND"


class TestChangePlan:
    def test_not_expired_when_fresh(self):
        target = CommandTarget(project_id="p1", device_id=1)
        plan = ChangePlan(
            plan_id="plan-1",
            target=target,
            operations=["interface GE1/0/1", "ip address 1.1.1.1 24"],
            baseline_hash="abc123",
        )
        assert plan.is_expired is False

    def test_is_immutable(self):
        target = CommandTarget(project_id="p1", device_id=1)
        plan = ChangePlan(
            plan_id="plan-1",
            target=target,
            operations=["cmd"],
            baseline_hash="abc",
        )
        with pytest.raises((TypeError, ValueError)):
            plan.plan_id = "changed"  # type: ignore


class TestAuditEvent:
    def test_create(self):
        evt = AuditEvent(
            event_id="evt-1",
            request_id="req-1",
            caller="test-user",
            tool="hcl_list_projects",
        )
        assert evt.tool == "hcl_list_projects"
        assert evt.caller == "test-user"
