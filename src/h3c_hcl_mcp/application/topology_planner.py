"""Deterministic, side-effect-free planning for isolated HCL topologies."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.topology_control import (
    DesiredTopology,
    HclControlCapabilities,
    ResourceBudget,
    ResourceEstimate,
    RiskLevel,
    TopologyOperation,
    TopologyOperationKind,
    TopologyPlan,
    canonical_topology_operations,
    topology_plan_content_hash,
)

Clock = Callable[[], datetime]
PlanIdFactory = Callable[[], str]


def _default_plan_id() -> str:
    return f"topology-{uuid4().hex}"


class TopologyPlanner:
    """Compile desired state into an immutable plan without performing I/O."""

    def __init__(
        self,
        model_memory_mb: Mapping[str, int],
        *,
        device_start_seconds: int = 120,
        plan_ttl_seconds: int = 300,
        clock: Clock | None = None,
        plan_id_factory: PlanIdFactory | None = None,
    ) -> None:
        if not model_memory_mb:
            raise ValueError("model_memory_mb must not be empty")
        copied_memory: dict[str, int] = {}
        for model, memory_mb in model_memory_mb.items():
            if not isinstance(model, str) or not model.strip() or model != model.strip():
                raise ValueError("model identifiers must be nonempty trimmed strings")
            if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or memory_mb <= 0:
                raise ValueError("model memory estimates must be positive integers")
            copied_memory[model] = memory_mb
        if (
            isinstance(device_start_seconds, bool)
            or not isinstance(device_start_seconds, int)
            or device_start_seconds <= 0
        ):
            raise ValueError("device_start_seconds must be a positive integer")
        if (
            isinstance(plan_ttl_seconds, bool)
            or not isinstance(plan_ttl_seconds, int)
            or plan_ttl_seconds <= 0
        ):
            raise ValueError("plan_ttl_seconds must be a positive integer")

        self._model_memory_mb = copied_memory
        self._device_start_seconds = device_start_seconds
        self._plan_ttl_seconds = plan_ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._plan_id_factory = plan_id_factory or _default_plan_id

    @staticmethod
    def _canonical_topology(desired: DesiredTopology) -> DesiredTopology:
        return DesiredTopology(
            project_name=desired.project_name,
            devices=tuple(sorted(desired.devices, key=lambda device: device.logical_id)),
            links=tuple(sorted(desired.links, key=lambda link: link.logical_id)),
        )

    @staticmethod
    def _operations(desired: DesiredTopology) -> tuple[TopologyOperation, ...]:
        return canonical_topology_operations(desired)

    @staticmethod
    def _required_kinds(operations: tuple[TopologyOperation, ...]) -> tuple[TopologyOperationKind, ...]:
        return tuple(sorted({operation.kind for operation in operations}, key=lambda kind: kind.value))

    def _estimate(self, desired: DesiredTopology, budget: ResourceBudget) -> ResourceEstimate:
        unknown_models = sorted(
            {device.model for device in desired.devices if device.model not in self._model_memory_mb}
        )
        if unknown_models:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Topology contains unsupported device models",
                details={"models": unknown_models},
            )

        device_count = len(desired.devices)
        operation_overhead_seconds = 5 * (1 + device_count + len(desired.links))
        return ResourceEstimate(
            device_count=device_count,
            link_count=len(desired.links),
            concurrent_starts=min(device_count, budget.max_concurrent_starts),
            estimated_memory_mb=sum(self._model_memory_mb[device.model] for device in desired.devices),
            estimated_total_seconds=(device_count * self._device_start_seconds) + operation_overhead_seconds,
        )

    @staticmethod
    def _enforce_budget(estimate: ResourceEstimate, budget: ResourceBudget) -> None:
        checks = (
            ("devices", estimate.device_count, budget.max_devices),
            ("links", estimate.link_count, budget.max_links),
            ("concurrent_starts", estimate.concurrent_starts, budget.max_concurrent_starts),
            ("estimated_memory_mb", estimate.estimated_memory_mb, budget.max_estimated_memory_mb),
            ("estimated_total_seconds", estimate.estimated_total_seconds, budget.max_total_seconds),
        )
        for resource, estimated, limit in checks:
            if estimated > limit:
                raise DomainError(
                    ErrorCode.POLICY_DENIED,
                    "Topology plan exceeds its resource budget",
                    details={"resource": resource, "estimate": estimated, "limit": limit},
                )

    def plan(
        self,
        desired: DesiredTopology,
        budget: ResourceBudget,
        capabilities: HclControlCapabilities,
    ) -> TopologyPlan:
        """Return a deterministic plan or fail before any provider side effect."""

        canonical_desired = self._canonical_topology(desired)
        operations = self._operations(canonical_desired)
        missing_operations = [
            kind.value for kind in self._required_kinds(operations) if not capabilities.supports(kind)
        ]
        if missing_operations:
            raise DomainError(
                ErrorCode.NOT_IMPLEMENTED,
                "HCL provider does not support required topology operations",
                details={"missing_operations": missing_operations},
            )

        unsupported_provider_models = sorted(
            {
                device.model
                for device in canonical_desired.devices
                if not capabilities.supports_model(device.model)
            }
        )
        if unsupported_provider_models:
            raise DomainError(
                ErrorCode.NOT_IMPLEMENTED,
                "HCL provider does not support requested device models",
                details={"models": unsupported_provider_models},
            )

        estimate = self._estimate(canonical_desired, budget)
        self._enforce_budget(estimate, budget)
        risk_level = RiskLevel.R2 if canonical_desired.devices else RiskLevel.R1

        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        created_at = created_at.astimezone(UTC)

        content_hash = topology_plan_content_hash(
            risk_level=risk_level,
            desired_topology=canonical_desired,
            operations=operations,
            budget=budget,
            estimate=estimate,
            provider_capabilities=capabilities,
            must_not_exist=True,
        )
        return TopologyPlan(
            plan_id=self._plan_id_factory(),
            content_hash=content_hash,
            risk_level=risk_level,
            desired_topology=canonical_desired,
            operations=operations,
            budget=budget,
            estimate=estimate,
            provider_capabilities=capabilities,
            must_not_exist=True,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self._plan_ttl_seconds),
        )
