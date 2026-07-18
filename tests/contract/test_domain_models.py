"""Contract tests for domain models — verify schemas and immutability."""

from datetime import UTC, datetime, timedelta

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
from h3c_hcl_mcp.domain.topology_control import (
    ABSENT_PROJECT_BASELINE_HASH,
    DesiredTopology,
    DeviceSpec,
    HclControlCapabilities,
    LinkEndpoint,
    LinkSpec,
    OperationContext,
    OperationReceipt,
    ResourceBudget,
    ResourceEstimate,
    RiskLevel,
    TopologyOperation,
    TopologyOperationKind,
    TopologyPlan,
    TopologySnapshot,
    canonical_topology_operations,
    operation_digest,
    topology_plan_content_hash,
)


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
        assert r.content_trust == "trusted_server_data"

    def test_untrusted_device_result(self):
        r = ToolResult.success(
            request_id="req-device",
            data={"raw_output": "device text"},
            content_trust="untrusted_device_output",
        )
        assert r.content_trust == "untrusted_device_output"

    def test_failure(self):
        r = ToolResult.failure(
            request_id="req-002",
            code="PROJECT_NOT_FOUND",
            message="Project p99 not found",
        )
        assert r.ok is False
        assert r.data is not None
        assert r.data["error"]["code"] == "PROJECT_NOT_FOUND"
        assert r.content_trust == "trusted_server_data"


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


class TestTopologyControlModels:
    def _desired_topology(self) -> DesiredTopology:
        return DesiredTopology(
            project_name="agent-lab",
            devices=(
                DeviceSpec(logical_id="core-1", name="CORE_1", model="S6850"),
                DeviceSpec(logical_id="edge-1", name="EDGE_1", model="MSR36-20"),
            ),
            links=(
                LinkSpec(
                    logical_id="core-edge",
                    endpoint_a=LinkEndpoint(device_logical_id="core-1", port="GE1/0/1"),
                    endpoint_b=LinkEndpoint(device_logical_id="edge-1", port="GE0/0"),
                ),
            ),
        )

    def _capabilities(self) -> HclControlCapabilities:
        return HclControlCapabilities(
            provider_name="windows-uia",
            provider_version="0.1",
            hcl_version="5.10.3",
            hcl_build="5.10.3-2024",
            ui_locale="zh-CN",
            session_fingerprint="1" * 64,
            probe_fingerprint="2" * 64,
            supported_operations=tuple(TopologyOperationKind),
            supported_models=("MSR36-20", "S6850"),
            interactive_required=True,
        )

    def _budget(self) -> ResourceBudget:
        return ResourceBudget(
            max_devices=2,
            max_links=1,
            max_concurrent_starts=1,
            max_estimated_memory_mb=4096,
            max_total_seconds=300,
        )

    def _estimate(self, **updates: int) -> ResourceEstimate:
        values = {
            "device_count": 2,
            "link_count": 1,
            "concurrent_starts": 1,
            "estimated_memory_mb": 2048,
            "estimated_total_seconds": 260,
        }
        values.update(updates)
        return ResourceEstimate(**values)

    def _plan(self, **updates: object) -> TopologyPlan:
        topology = self._desired_topology()
        operations = canonical_topology_operations(topology)
        budget = self._budget()
        estimate = self._estimate()
        capabilities = self._capabilities()
        values: dict[str, object] = {
            "plan_id": "plan-1",
            "risk_level": RiskLevel.R2,
            "desired_topology": topology,
            "operations": operations,
            "budget": budget,
            "estimate": estimate,
            "provider_capabilities": capabilities,
            "must_not_exist": True,
            "created_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
        values.update(updates)
        values["content_hash"] = topology_plan_content_hash(
            risk_level=values["risk_level"],  # type: ignore[arg-type]
            desired_topology=values["desired_topology"],  # type: ignore[arg-type]
            operations=values["operations"],  # type: ignore[arg-type]
            budget=values["budget"],  # type: ignore[arg-type]
            estimate=values["estimate"],  # type: ignore[arg-type]
            provider_capabilities=values["provider_capabilities"],  # type: ignore[arg-type]
            must_not_exist=values["must_not_exist"],  # type: ignore[arg-type]
        )
        if "content_hash" in updates:
            values["content_hash"] = updates["content_hash"]
        return TopologyPlan(**values)  # type: ignore[arg-type]

    def _context(self, **updates: object) -> OperationContext:
        operation = canonical_topology_operations(self._desired_topology())[0]
        issued_at = datetime.now(UTC)
        values: dict[str, object] = {
            "transaction_id": "tx-1",
            "idempotency_key": "idem-1",
            "execution_grant_id": "grant-1",
            "project_name": "agent-lab",
            "plan_id": "plan-1",
            "content_hash": "a" * 64,
            "expected_baseline_hash": ABSENT_PROJECT_BASELINE_HASH,
            "operation_index": 0,
            "operation_digest": operation_digest(operation),
            "fencing_token": 7,
            "issued_at": issued_at,
            "deadline": issued_at + timedelta(minutes=5),
        }
        values.update(updates)
        return OperationContext(**values)  # type: ignore[arg-type]

    def test_risk_levels_are_stable(self):
        assert [level.value for level in RiskLevel] == ["R0", "R1", "R2", "R3"]

    @pytest.mark.parametrize(
        "field",
        [
            "max_devices",
            "max_links",
            "max_concurrent_starts",
            "max_estimated_memory_mb",
            "max_total_seconds",
        ],
    )
    def test_resource_budget_requires_positive_limits(self, field: str):
        values = {
            "max_devices": 2,
            "max_links": 1,
            "max_concurrent_starts": 1,
            "max_estimated_memory_mb": 4096,
            "max_total_seconds": 300,
        }
        values[field] = 0
        with pytest.raises(ValueError):
            ResourceBudget(**values)

    def test_desired_topology_is_deeply_immutable(self):
        topology = self._desired_topology()

        assert isinstance(topology.devices, tuple)
        assert isinstance(topology.links, tuple)
        with pytest.raises((TypeError, ValueError)):
            topology.devices = ()  # type: ignore[misc]
        with pytest.raises((TypeError, ValueError)):
            topology.devices[0].name = "changed"  # type: ignore[misc]

    @pytest.mark.parametrize("project_name", ["CON", "../lab", "lab\\other", "lab\nname", "lab "])
    def test_desired_topology_rejects_unsafe_windows_project_names(self, project_name: str):
        with pytest.raises(ValueError):
            DesiredTopology(project_name=project_name)

    def test_desired_topology_rejects_device_names_colliding_on_windows(self):
        with pytest.raises(ValueError, match="Windows identity"):
            DesiredTopology(
                project_name="safe-lab",
                devices=(
                    DeviceSpec(logical_id="r1", name="Router", model="MSR36"),
                    DeviceSpec(logical_id="r2", name="router", model="MSR36"),
                ),
            )

    def test_topology_identifiers_and_undirected_links_are_canonical(self):
        link = LinkSpec(
            logical_id="R2-R1",
            endpoint_a=LinkEndpoint(device_logical_id="R2", port="ge0/1"),
            endpoint_b=LinkEndpoint(device_logical_id="R1", port="ge0/0"),
        )

        assert link.logical_id == "r2-r1"
        assert link.endpoint_a.device_logical_id == "r1"
        assert link.endpoint_a.port == "GE0/0"
        assert link.endpoint_b.device_logical_id == "r2"

    def test_desired_topology_rejects_duplicate_device_logical_ids(self):
        with pytest.raises(ValueError, match="device logical IDs must be unique"):
            DesiredTopology(
                project_name="duplicate-devices",
                devices=(
                    DeviceSpec(logical_id="r1", name="R1", model="MSR"),
                    DeviceSpec(logical_id="r1", name="R2", model="MSR"),
                ),
            )

    def test_desired_topology_rejects_duplicate_link_logical_ids(self):
        link = LinkSpec(
            logical_id="link-1",
            endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
            endpoint_b=LinkEndpoint(device_logical_id="r2", port="GE0/0"),
        )
        with pytest.raises(ValueError, match="link logical IDs must be unique"):
            DesiredTopology(
                project_name="duplicate-links",
                devices=(
                    DeviceSpec(logical_id="r1", name="R1", model="MSR"),
                    DeviceSpec(logical_id="r2", name="R2", model="MSR"),
                ),
                links=(link, link),
            )

    def test_desired_topology_rejects_missing_link_endpoint(self):
        with pytest.raises(ValueError, match="link endpoint device does not exist: missing"):
            DesiredTopology(
                project_name="missing-endpoint",
                devices=(DeviceSpec(logical_id="r1", name="R1", model="MSR"),),
                links=(
                    LinkSpec(
                        logical_id="link-1",
                        endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
                        endpoint_b=LinkEndpoint(device_logical_id="missing", port="GE0/0"),
                    ),
                ),
            )

    def test_desired_topology_rejects_reused_device_port(self):
        with pytest.raises(ValueError, match="topology port is already occupied: r1:GE0/0"):
            DesiredTopology(
                project_name="reused-port",
                devices=(
                    DeviceSpec(logical_id="r1", name="R1", model="MSR"),
                    DeviceSpec(logical_id="r2", name="R2", model="MSR"),
                    DeviceSpec(logical_id="r3", name="R3", model="MSR"),
                ),
                links=(
                    LinkSpec(
                        logical_id="link-1",
                        endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
                        endpoint_b=LinkEndpoint(device_logical_id="r2", port="GE0/0"),
                    ),
                    LinkSpec(
                        logical_id="link-2",
                        endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
                        endpoint_b=LinkEndpoint(device_logical_id="r3", port="GE0/0"),
                    ),
                ),
            )

    @pytest.mark.parametrize(
        ("kind", "payload"),
        [
            (TopologyOperationKind.CREATE_PROJECT, {"project_name": "agent-lab"}),
            (
                TopologyOperationKind.ADD_DEVICE,
                {"device": DeviceSpec(logical_id="r1", name="R1", model="MSR")},
            ),
            (
                TopologyOperationKind.CONNECT_LINK,
                {
                    "link": LinkSpec(
                        logical_id="link-1",
                        endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
                        endpoint_b=LinkEndpoint(device_logical_id="r2", port="GE0/0"),
                    )
                },
            ),
            (TopologyOperationKind.START_DEVICE, {"device_logical_id": "r1"}),
        ],
    )
    def test_topology_operation_supports_only_structured_kinds(
        self,
        kind: TopologyOperationKind,
        payload: dict[str, object],
    ):
        operation = TopologyOperation(kind=kind, **payload)
        assert operation.kind is kind

    def test_topology_operation_rejects_arbitrary_command_and_private_protocol_fields(self):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            TopologyOperation(
                kind=TopologyOperationKind.START_DEVICE,
                device_logical_id="r1",
                command="private-start r1",  # type: ignore[call-arg]
                private_protocol={"opcode": 1},  # type: ignore[call-arg]
            )

    def test_topology_operation_requires_kind_specific_payload(self):
        with pytest.raises(ValueError, match="start_device requires only device_logical_id"):
            TopologyOperation(kind=TopologyOperationKind.START_DEVICE, project_name="wrong")

    def test_topology_plan_is_immutable_and_within_budget(self):
        plan = self._plan()

        assert plan.is_expired is False
        assert isinstance(plan.operations, tuple)
        assert plan.must_not_exist is True
        with pytest.raises((TypeError, ValueError)):
            plan.plan_id = "changed"  # type: ignore[misc]

    def test_topology_plan_rejects_forged_hash(self):
        with pytest.raises(ValueError, match="content_hash does not match"):
            self._plan(content_hash="f" * 64)

    @pytest.mark.parametrize(
        ("update", "message"),
        [
            (
                {
                    "estimate": ResourceEstimate(
                        device_count=3,
                        link_count=1,
                        concurrent_starts=1,
                        estimated_memory_mb=2048,
                        estimated_total_seconds=260,
                    )
                },
                "device estimate does not match",
            ),
            ({"operations": ()}, "operations must match"),
            ({"risk_level": RiskLevel.R1}, "risk_level does not match"),
            ({"must_not_exist": False}, "Input should be True"),
        ],
    )
    def test_topology_plan_rejects_forged_execution_fields(self, update: dict[str, object], message: str):
        with pytest.raises(ValueError, match=message):
            self._plan(**update)

    def test_revalidate_for_execution_detects_unsafe_model_copy(self):
        forged = self._plan().model_copy(update={"operations": ()})

        with pytest.raises(ValueError, match="operations must match"):
            forged.revalidate_for_execution()

    def test_plan_hash_binds_estimate_risk_and_capability_fingerprint(self):
        base = self._plan()
        changed_estimate = self._plan(estimate=self._estimate(estimated_memory_mb=2049))
        changed_capabilities = self._plan(
            provider_capabilities=self._capabilities().model_copy(update={"probe_fingerprint": "3" * 64})
        )

        assert base.content_hash != changed_estimate.content_hash
        assert base.content_hash != changed_capabilities.content_hash

    def test_topology_plan_requires_expiry_after_creation(self):
        created_at = datetime.now(UTC)
        with pytest.raises(ValueError, match="expires_at must be later than created_at"):
            self._plan(created_at=created_at, expires_at=created_at)

    def test_topology_plan_expiry_uses_utc(self):
        plan = self._plan(
            created_at=datetime.now(UTC) - timedelta(minutes=10),
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        assert plan.is_expired is True

    def test_hcl_control_capabilities_are_immutable_and_queryable(self):
        capabilities = self._capabilities()

        assert capabilities.supports(TopologyOperationKind.CREATE_PROJECT) is True
        assert capabilities.supports_model("s6850") is True
        assert isinstance(capabilities.supported_operations, tuple)
        with pytest.raises((TypeError, ValueError)):
            capabilities.provider_name = "changed"  # type: ignore[misc]

    def test_hcl_control_capabilities_reject_duplicate_operations(self):
        with pytest.raises(ValueError, match="supported_operations must be unique"):
            HclControlCapabilities.model_validate(
                self._capabilities().model_dump()
                | {
                    "supported_operations": (
                        TopologyOperationKind.START_DEVICE,
                        TopologyOperationKind.START_DEVICE,
                    )
                }
            )

    def test_topology_snapshot_tracks_only_devices_in_topology(self):
        captured_at = datetime.now(UTC)
        snapshot = TopologySnapshot(
            project_name="agent-lab",
            topology=self._desired_topology(),
            baseline_hash="e" * 64,
            captured_at=captured_at,
            running_device_logical_ids=("core-1",),
        )

        assert snapshot.captured_at == captured_at
        assert snapshot.running_device_logical_ids == ("core-1",)
        with pytest.raises(ValueError, match="running device does not exist in topology: missing"):
            TopologySnapshot(
                project_name="agent-lab",
                topology=self._desired_topology(),
                baseline_hash="e" * 64,
                captured_at=captured_at,
                running_device_logical_ids=("missing",),
            )

    def test_topology_snapshot_rejects_duplicate_running_devices(self):
        with pytest.raises(ValueError, match="running device logical IDs must be unique"):
            TopologySnapshot(
                project_name="agent-lab",
                topology=self._desired_topology(),
                baseline_hash="e" * 64,
                captured_at=datetime.now(UTC),
                running_device_logical_ids=("core-1", "CORE-1"),
            )

    def test_topology_snapshot_requires_matching_project_name(self):
        with pytest.raises(ValueError, match="snapshot project_name must match topology project_name"):
            TopologySnapshot(
                project_name="different-lab",
                topology=self._desired_topology(),
                baseline_hash="e" * 64,
                captured_at=datetime.now(UTC),
            )

    def test_control_models_reject_naive_timestamps(self):
        with pytest.raises(ValueError, match="captured_at must be timezone-aware"):
            TopologySnapshot(
                project_name="agent-lab",
                topology=self._desired_topology(),
                baseline_hash="e" * 64,
                captured_at=datetime.now(),
            )
        with pytest.raises(ValueError, match="operation context timestamps must be timezone-aware"):
            self._context(deadline=datetime.now())
        context = self._context()
        with pytest.raises(ValueError, match="completed_at must be timezone-aware"):
            OperationReceipt(
                kind=TopologyOperationKind.CREATE_PROJECT,
                context=context,
                operation_digest=context.operation_digest,
                changed=True,
                checkpoint_hash="b" * 64,
                completed_at=datetime.now(),
            )

    def test_operation_context_is_immutable_and_requires_positive_fencing_token(self):
        context = self._context()
        assert context.fencing_token == 7
        assert context.plan_id == "plan-1"
        assert context.expected_baseline_hash == ABSENT_PROJECT_BASELINE_HASH
        with pytest.raises((TypeError, ValueError)):
            context.fencing_token = 8  # type: ignore[misc]
        with pytest.raises(ValueError):
            self._context(fencing_token=0)

    def test_operation_context_rejects_expired_or_invalid_window(self):
        now = datetime.now(UTC)
        expired = self._context(
            issued_at=now - timedelta(minutes=2),
            deadline=now - timedelta(minutes=1),
        )
        assert expired.is_expired is True
        with pytest.raises(ValueError, match="deadline must be later"):
            self._context(issued_at=now, deadline=now)

    def test_operation_receipt_is_deeply_immutable(self):
        context = self._context()
        receipt = OperationReceipt(
            kind=TopologyOperationKind.CONNECT_LINK,
            context=context,
            operation_digest=context.operation_digest,
            changed=True,
            checkpoint_hash="b" * 64,
            completed_at=datetime.now(UTC),
            warning_codes=("INTERACTIVE_CONFIRMATION",),
        )

        assert receipt.context.execution_grant_id == "grant-1"
        assert isinstance(receipt.warning_codes, tuple)
        with pytest.raises((TypeError, ValueError)):
            receipt.warning_codes = ()  # type: ignore[misc]

    def test_operation_receipt_rejects_digest_or_time_mismatch(self):
        context = self._context()
        with pytest.raises(ValueError, match="digest does not match"):
            OperationReceipt(
                kind=TopologyOperationKind.START_DEVICE,
                context=context,
                operation_digest="c" * 64,
                changed=False,
                checkpoint_hash="b" * 64,
                completed_at=context.issued_at,
            )
        with pytest.raises(ValueError, match="outside the operation context"):
            OperationReceipt(
                kind=TopologyOperationKind.START_DEVICE,
                context=context,
                operation_digest=context.operation_digest,
                changed=False,
                checkpoint_hash="b" * 64,
                completed_at=context.deadline + timedelta(seconds=1),
            )

    @pytest.mark.parametrize("warning", ["free form", "C:\\secret", "lowercase"])
    def test_operation_receipt_rejects_free_text_warning_channels(self, warning: str):
        context = self._context()
        with pytest.raises(ValueError, match="safe symbolic codes"):
            OperationReceipt(
                kind=TopologyOperationKind.CREATE_PROJECT,
                context=context,
                operation_digest=context.operation_digest,
                changed=True,
                checkpoint_hash="b" * 64,
                completed_at=context.issued_at,
                warning_codes=(warning,),
            )

    @pytest.mark.parametrize(
        ("model", "values"),
        [
            (
                HclControlCapabilities,
                {
                    "provider_name": "provider",
                    "provider_version": "1",
                    "hcl_version": "5.10",
                    "hcl_build": "5.10.3-2024",
                    "ui_locale": "zh-CN",
                    "session_fingerprint": "1" * 64,
                    "probe_fingerprint": "2" * 64,
                    "supported_operations": (),
                    "supported_models": (),
                    "interactive_required": False,
                },
            ),
            (
                OperationContext,
                {},
            ),
            (
                OperationReceipt,
                {},
            ),
        ],
    )
    def test_new_control_models_forbid_extra_fields(
        self,
        model: type[object],
        values: dict[str, object],
    ):
        if model is OperationContext:
            values.update(self._context().model_dump())
        elif model is OperationReceipt:
            context = self._context()
            values.update(
                OperationReceipt(
                    kind=TopologyOperationKind.ADD_DEVICE,
                    context=context,
                    operation_digest=context.operation_digest,
                    changed=True,
                    checkpoint_hash="b" * 64,
                    completed_at=context.issued_at,
                ).model_dump()
            )
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            model(**values, arbitrary_command="not allowed")  # type: ignore[call-arg]
