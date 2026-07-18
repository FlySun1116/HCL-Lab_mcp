"""Tests for deterministic, side-effect-free HCL topology planning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from h3c_hcl_mcp.application.topology_planner import TopologyPlanner
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.topology_control import (
    DesiredTopology,
    DeviceSpec,
    HclControlCapabilities,
    LinkEndpoint,
    LinkSpec,
    ResourceBudget,
    TopologyOperationKind,
)

NOW = datetime(2026, 7, 18, 6, 0, tzinfo=UTC)
ALL_OPERATIONS = tuple(TopologyOperationKind)


def _capabilities(*operations: TopologyOperationKind) -> HclControlCapabilities:
    return HclControlCapabilities(
        provider_name="windows-uia",
        provider_version="0.1",
        hcl_version="5.10.3",
        hcl_build="5.10.3-2024",
        ui_locale="zh-CN",
        session_fingerprint="1" * 64,
        probe_fingerprint="2" * 64,
        supported_operations=operations or ALL_OPERATIONS,
        supported_models=("MSR36",),
        interactive_required=True,
    )


def _budget(**updates: int) -> ResourceBudget:
    values = {
        "max_devices": 4,
        "max_links": 4,
        "max_concurrent_starts": 1,
        "max_estimated_memory_mb": 4096,
        "max_total_seconds": 600,
    }
    values.update(updates)
    return ResourceBudget(**values)


def _topology(*, reversed_order: bool = False) -> DesiredTopology:
    devices = (
        DeviceSpec(logical_id="r2", name="R2", model="MSR36"),
        DeviceSpec(logical_id="r1", name="R1", model="MSR36"),
    )
    links = (
        LinkSpec(
            logical_id="r1-r2",
            endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
            endpoint_b=LinkEndpoint(device_logical_id="r2", port="GE0/0"),
        ),
    )
    return DesiredTopology(
        project_name="MCP_SMOKE_LAB",
        devices=tuple(reversed(devices)) if reversed_order else devices,
        links=links,
    )


def _planner(memory: dict[str, int] | None = None, **kwargs: object) -> TopologyPlanner:
    return TopologyPlanner(
        memory or {"MSR36": 768},
        clock=lambda: NOW,
        plan_id_factory=lambda: "plan-fixed",
        **kwargs,  # type: ignore[arg-type]
    )


def test_plan_orders_structured_operations_and_estimates_resources() -> None:
    plan = _planner().plan(_topology(), _budget(), _capabilities())

    assert [operation.kind for operation in plan.operations] == [
        TopologyOperationKind.CREATE_PROJECT,
        TopologyOperationKind.ADD_DEVICE,
        TopologyOperationKind.ADD_DEVICE,
        TopologyOperationKind.CONNECT_LINK,
        TopologyOperationKind.START_DEVICE,
        TopologyOperationKind.START_DEVICE,
    ]
    assert [operation.device.logical_id for operation in plan.operations[1:3] if operation.device] == [
        "r1",
        "r2",
    ]
    assert [
        operation.device_logical_id for operation in plan.operations[-2:] if operation.device_logical_id
    ] == ["r1", "r2"]
    assert plan.estimate.device_count == 2
    assert plan.estimate.link_count == 1
    assert plan.estimate.concurrent_starts == 1
    assert plan.estimate.estimated_memory_mb == 1536
    assert plan.estimate.estimated_total_seconds == 260
    assert plan.risk_level.value == "R2"
    assert plan.created_at == NOW
    assert int((plan.expires_at - plan.created_at).total_seconds()) == 300


def test_canonical_hash_ignores_input_device_order_and_plan_identity() -> None:
    first = _planner().plan(_topology(), _budget(), _capabilities())
    second = TopologyPlanner(
        {"MSR36": 768},
        clock=lambda: datetime(2026, 7, 18, 7, 0, tzinfo=UTC),
        plan_id_factory=lambda: "different-plan",
    ).plan(_topology(reversed_order=True), _budget(), _capabilities())

    assert first.content_hash == second.content_hash
    assert first.plan_id != second.plan_id
    assert first.created_at != second.created_at


def test_hash_binds_provider_capability_and_budget() -> None:
    base = _planner().plan(_topology(), _budget(), _capabilities())
    changed_provider = _planner().plan(
        _topology(),
        _budget(),
        HclControlCapabilities(
            provider_name="windows-uia",
            provider_version="0.2",
            hcl_version="5.10.3",
            hcl_build="5.10.3-2024",
            ui_locale="zh-CN",
            session_fingerprint="1" * 64,
            probe_fingerprint="2" * 64,
            supported_operations=ALL_OPERATIONS,
            supported_models=("MSR36",),
            interactive_required=True,
        ),
    )
    changed_budget = _planner().plan(_topology(), _budget(max_total_seconds=601), _capabilities())

    assert len(base.content_hash) == 64
    assert base.content_hash != changed_provider.content_hash
    assert base.content_hash != changed_budget.content_hash


def test_empty_topology_creates_only_project_at_r1() -> None:
    desired = DesiredTopology(project_name="EMPTY_LAB")
    plan = _planner().plan(
        desired,
        _budget(),
        _capabilities(TopologyOperationKind.CREATE_PROJECT),
    )

    assert [operation.kind for operation in plan.operations] == [TopologyOperationKind.CREATE_PROJECT]
    assert plan.risk_level.value == "R1"
    assert plan.estimate.device_count == 0
    assert plan.estimate.estimated_memory_mb == 0


def test_missing_provider_capabilities_fail_before_planning() -> None:
    with pytest.raises(DomainError) as caught:
        _planner().plan(
            _topology(),
            _budget(),
            _capabilities(TopologyOperationKind.CREATE_PROJECT),
        )

    assert caught.value.code == ErrorCode.NOT_IMPLEMENTED
    assert caught.value.details == {"missing_operations": ["add_device", "connect_link", "start_device"]}


def test_unknown_models_are_rejected_without_local_data() -> None:
    with pytest.raises(DomainError) as caught:
        _planner({"S6850": 1024}).plan(_topology(), _budget(), _capabilities())

    assert caught.value.code == ErrorCode.INVALID_ARGUMENT
    assert caught.value.details == {"models": ["MSR36"]}


def test_provider_model_capability_is_checked_before_local_estimation() -> None:
    capabilities = _capabilities().model_copy(update={"supported_models": ("S6850",)})

    with pytest.raises(DomainError) as caught:
        _planner().plan(_topology(), _budget(), capabilities)

    assert caught.value.code == ErrorCode.NOT_IMPLEMENTED
    assert caught.value.details == {"models": ["MSR36"]}


def test_hash_binds_resource_estimate() -> None:
    base = _planner().plan(_topology(), _budget(), _capabilities())
    changed = _planner({"MSR36": 769}).plan(_topology(), _budget(), _capabilities())

    assert base.estimate != changed.estimate
    assert base.content_hash != changed.content_hash


@pytest.mark.parametrize(
    ("budget", "resource", "estimate", "limit"),
    [
        (_budget(max_devices=1), "devices", 2, 1),
        (_budget(max_estimated_memory_mb=1500), "estimated_memory_mb", 1536, 1500),
        (_budget(max_total_seconds=250), "estimated_total_seconds", 260, 250),
    ],
)
def test_resource_budget_rejection_is_structured(
    budget: ResourceBudget,
    resource: str,
    estimate: int,
    limit: int,
) -> None:
    with pytest.raises(DomainError) as caught:
        _planner().plan(_topology(), budget, _capabilities())

    assert caught.value.code == ErrorCode.POLICY_DENIED
    assert caught.value.details == {"resource": resource, "estimate": estimate, "limit": limit}


def test_link_budget_rejection_is_structured() -> None:
    desired = DesiredTopology(
        project_name="LINK_BUDGET_LAB",
        devices=(
            DeviceSpec(logical_id="r1", name="R1", model="MSR36"),
            DeviceSpec(logical_id="r2", name="R2", model="MSR36"),
            DeviceSpec(logical_id="r3", name="R3", model="MSR36"),
        ),
        links=(
            LinkSpec(
                logical_id="r1-r2",
                endpoint_a=LinkEndpoint(device_logical_id="r1", port="GE0/0"),
                endpoint_b=LinkEndpoint(device_logical_id="r2", port="GE0/0"),
            ),
            LinkSpec(
                logical_id="r2-r3",
                endpoint_a=LinkEndpoint(device_logical_id="r2", port="GE0/1"),
                endpoint_b=LinkEndpoint(device_logical_id="r3", port="GE0/0"),
            ),
        ),
    )

    with pytest.raises(DomainError) as caught:
        _planner().plan(desired, _budget(max_links=1), _capabilities())

    assert caught.value.code == ErrorCode.POLICY_DENIED
    assert caught.value.details == {"resource": "links", "estimate": 2, "limit": 1}


def test_model_memory_mapping_is_defensively_copied() -> None:
    memory = {"MSR36": 768}
    planner = _planner(memory)
    memory["MSR36"] = 9999

    assert planner.plan(_topology(), _budget(), _capabilities()).estimate.estimated_memory_mb == 1536


@pytest.mark.parametrize(
    "memory",
    [{}, {"": 128}, {" MSR36": 128}, {"MSR36": 0}, {"MSR36": -1}, {"MSR36": True}],
)
def test_invalid_model_memory_map_is_rejected(memory: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TopologyPlanner(memory)


def test_naive_clock_is_rejected() -> None:
    planner = TopologyPlanner(
        {"MSR36": 768},
        clock=lambda: datetime(2026, 7, 18, 6, 0),
        plan_id_factory=lambda: "plan-fixed",
    )

    with pytest.raises(ValueError, match="clock must return a timezone-aware datetime"):
        planner.plan(_topology(), _budget(), _capabilities())
