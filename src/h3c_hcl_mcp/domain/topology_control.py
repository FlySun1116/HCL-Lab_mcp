"""Immutable contracts for the future HCL topology control plane.

The module deliberately contains no HCL private protocol, filesystem path,
window handle, or arbitrary command field.  Every execution-bound object can
be reconstructed through Pydantic to detect unsafe ``model_copy`` mutations.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode

_LOGICAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
_MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$"
_PORT_PATTERN = r"^[A-Za-z][A-Za-z0-9/_.-]*$"
_OPAQUE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_WINDOWS_INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)

# A public, deterministic sentinel for "the project must not exist".  It is
# not a secret or an actual empty-project snapshot hash.
ABSENT_PROJECT_BASELINE_HASH = hashlib.sha256(b"hcl-project-absent-v1").hexdigest()


def _contains_control(value: str) -> bool:
    return any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F or character in {"\u2028", "\u2029"}
        for character in value
    )


def _canonical_windows_name(value: str, *, label: str) -> str:
    if value != value.strip():
        raise ValueError(f"{label} must not start or end with whitespace")
    normalized = unicodedata.normalize("NFKC", value)
    if _contains_control(normalized) or any(char in _WINDOWS_INVALID_NAME_CHARS for char in normalized):
        raise ValueError(f"{label} contains unsafe characters")
    if normalized.endswith((" ", ".")):
        raise ValueError(f"{label} must not end with a space or dot")
    reserved_stem = normalized.split(".", maxsplit=1)[0].upper()
    if reserved_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} is a reserved Windows name")
    return normalized


def _windows_identity(value: str) -> str:
    return ntpath.normcase(unicodedata.normalize("NFKC", value))


def _aware_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class RiskLevel(StrEnum):
    """Stable topology-control risk levels."""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class TopologyOperationKind(StrEnum):
    """Structured operation kinds supported by the first control contract."""

    CREATE_PROJECT = "create_project"
    ADD_DEVICE = "add_device"
    CONNECT_LINK = "connect_link"
    START_DEVICE = "start_device"


class ResourceBudget(BaseModel):
    """Hard positive limits approved for one topology plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_devices: int = Field(gt=0)
    max_links: int = Field(gt=0)
    max_concurrent_starts: int = Field(gt=0)
    max_estimated_memory_mb: int = Field(gt=0)
    max_total_seconds: int = Field(gt=0)


class ResourceEstimate(BaseModel):
    """Bounded resource estimate produced before topology execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    concurrent_starts: int = Field(ge=0)
    estimated_memory_mb: int = Field(ge=0)
    estimated_total_seconds: int = Field(ge=0)


class DeviceSpec(BaseModel):
    """One desired HCL device addressed by a plan-local logical ID."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_id: str = Field(min_length=1, max_length=128, pattern=_LOGICAL_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128, pattern=_MODEL_PATTERN)

    @field_validator("logical_id")
    @classmethod
    def canonicalize_logical_id(cls, value: str) -> str:
        return value.lower()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_windows_name(value, label="device name")


class LinkEndpoint(BaseModel):
    """A desired link endpoint using only logical topology identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_logical_id: str = Field(min_length=1, max_length=128, pattern=_LOGICAL_ID_PATTERN)
    port: str = Field(min_length=1, max_length=128, pattern=_PORT_PATTERN)

    @field_validator("device_logical_id")
    @classmethod
    def canonicalize_device_id(cls, value: str) -> str:
        return value.lower()

    @field_validator("port")
    @classmethod
    def canonicalize_port(cls, value: str) -> str:
        return value.upper()


class LinkSpec(BaseModel):
    """A canonical, undirected point-to-point link between two device ports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_id: str = Field(min_length=1, max_length=128, pattern=_LOGICAL_ID_PATTERN)
    endpoint_a: LinkEndpoint
    endpoint_b: LinkEndpoint

    @field_validator("logical_id")
    @classmethod
    def canonicalize_logical_id(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def canonicalize_endpoints(self) -> Self:
        endpoint_a_key = (self.endpoint_a.device_logical_id, self.endpoint_a.port)
        endpoint_b_key = (self.endpoint_b.device_logical_id, self.endpoint_b.port)
        if endpoint_a_key == endpoint_b_key:
            raise ValueError("link endpoints must be distinct")
        if endpoint_b_key < endpoint_a_key:
            old_a = self.endpoint_a
            object.__setattr__(self, "endpoint_a", self.endpoint_b)
            object.__setattr__(self, "endpoint_b", old_a)
        return self


class DesiredTopology(BaseModel):
    """Deeply immutable and canonical desired HCL topology."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: str = Field(min_length=1, max_length=128)
    devices: tuple[DeviceSpec, ...] = ()
    links: tuple[LinkSpec, ...] = ()

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        return _canonical_windows_name(value, label="project name")

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        device_ids = [device.logical_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device logical IDs must be unique")

        device_name_ids = [_windows_identity(device.name) for device in self.devices]
        if len(device_name_ids) != len(set(device_name_ids)):
            raise ValueError("device names must be unique under Windows identity rules")

        link_ids = [link.logical_id for link in self.links]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("link logical IDs must be unique")

        known_devices = set(device_ids)
        occupied_ports: set[tuple[str, str]] = set()
        for link in self.links:
            for endpoint in (link.endpoint_a, link.endpoint_b):
                if endpoint.device_logical_id not in known_devices:
                    raise ValueError(f"link endpoint device does not exist: {endpoint.device_logical_id}")
                port_key = (endpoint.device_logical_id, endpoint.port)
                if port_key in occupied_ports:
                    raise ValueError(
                        f"topology port is already occupied: {endpoint.device_logical_id}:{endpoint.port}"
                    )
                occupied_ports.add(port_key)

        object.__setattr__(self, "devices", tuple(sorted(self.devices, key=lambda item: item.logical_id)))
        object.__setattr__(self, "links", tuple(sorted(self.links, key=lambda item: item.logical_id)))
        return self


class TopologyOperation(BaseModel):
    """One structured topology operation without raw-command escape hatches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TopologyOperationKind
    project_name: str | None = Field(default=None, min_length=1, max_length=128)
    device: DeviceSpec | None = None
    link: LinkSpec | None = None
    device_logical_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=_LOGICAL_ID_PATTERN,
    )

    @field_validator("project_name")
    @classmethod
    def validate_optional_project_name(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_windows_name(value, label="project name")

    @field_validator("device_logical_id")
    @classmethod
    def canonicalize_optional_device_id(cls, value: str | None) -> str | None:
        return None if value is None else value.lower()

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        present = {
            "project_name": self.project_name is not None,
            "device": self.device is not None,
            "link": self.link is not None,
            "device_logical_id": self.device_logical_id is not None,
        }
        required_by_kind = {
            TopologyOperationKind.CREATE_PROJECT: "project_name",
            TopologyOperationKind.ADD_DEVICE: "device",
            TopologyOperationKind.CONNECT_LINK: "link",
            TopologyOperationKind.START_DEVICE: "device_logical_id",
        }
        required = required_by_kind[self.kind]
        if not present[required] or any(
            is_present for field_name, is_present in present.items() if field_name != required
        ):
            raise ValueError(f"{self.kind.value} requires only {required}")
        return self


def canonical_topology_operations(desired: DesiredTopology) -> tuple[TopologyOperation, ...]:
    """Build the sole valid create-only operation sequence for the first milestone."""

    operations: list[TopologyOperation] = [
        TopologyOperation(
            kind=TopologyOperationKind.CREATE_PROJECT,
            project_name=desired.project_name,
        )
    ]
    operations.extend(
        TopologyOperation(kind=TopologyOperationKind.ADD_DEVICE, device=device) for device in desired.devices
    )
    operations.extend(
        TopologyOperation(kind=TopologyOperationKind.CONNECT_LINK, link=link) for link in desired.links
    )
    operations.extend(
        TopologyOperation(
            kind=TopologyOperationKind.START_DEVICE,
            device_logical_id=device.logical_id,
        )
        for device in desired.devices
    )
    return tuple(operations)


def operation_digest(operation: TopologyOperation) -> str:
    """Return a canonical digest that a Provider receipt must echo."""

    payload = json.dumps(
        operation.model_dump(mode="json", exclude_none=True),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HclControlCapabilities(BaseModel):
    """Version- and session-bound capability declaration for one Provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    provider_version: str = Field(min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    hcl_version: str = Field(min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    hcl_build: str = Field(min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    ui_locale: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    session_fingerprint: str = Field(pattern=_HASH_PATTERN)
    probe_fingerprint: str = Field(pattern=_HASH_PATTERN)
    supported_operations: tuple[TopologyOperationKind, ...] = ()
    supported_models: tuple[str, ...] = ()
    interactive_required: bool

    @field_validator("supported_models")
    @classmethod
    def validate_models(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not model or len(model) > 128 for model in value):
            raise ValueError("supported_models must contain bounded model identifiers")
        if any(
            not model[0].isalnum() or not all(char.isalnum() or char in "_.+-" for char in model)
            for model in value
        ):
            raise ValueError("supported_models contains an unsafe model identifier")
        if len({_windows_identity(model) for model in value}) != len(value):
            raise ValueError("supported_models must be unique")
        return tuple(sorted(value, key=_windows_identity))

    @model_validator(mode="after")
    def validate_supported_operations(self) -> Self:
        if len(self.supported_operations) != len(set(self.supported_operations)):
            raise ValueError("supported_operations must be unique")
        object.__setattr__(
            self,
            "supported_operations",
            tuple(sorted(self.supported_operations, key=lambda kind: kind.value)),
        )
        return self

    def supports(self, kind: TopologyOperationKind) -> bool:
        return kind in self.supported_operations

    def supports_model(self, model: str) -> bool:
        identity = _windows_identity(model)
        return any(_windows_identity(candidate) == identity for candidate in self.supported_models)


def topology_plan_content_hash(
    *,
    risk_level: RiskLevel,
    desired_topology: DesiredTopology,
    operations: tuple[TopologyOperation, ...],
    budget: ResourceBudget,
    estimate: ResourceEstimate,
    provider_capabilities: HclControlCapabilities,
    must_not_exist: bool,
) -> str:
    """Hash every execution-relevant immutable plan field."""

    payload: dict[str, Any] = {
        "risk_level": risk_level.value,
        "desired_topology": desired_topology.model_dump(mode="json"),
        "operations": [item.model_dump(mode="json", exclude_none=True) for item in operations],
        "budget": budget.model_dump(mode="json"),
        "estimate": estimate.model_dump(mode="json"),
        "provider_capabilities": provider_capabilities.model_dump(mode="json"),
        "must_not_exist": must_not_exist,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TopologyPlan(BaseModel):
    """Self-validating, create-only topology plan for an isolated project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    risk_level: RiskLevel
    desired_topology: DesiredTopology
    operations: tuple[TopologyOperation, ...]
    budget: ResourceBudget
    estimate: ResourceEstimate
    provider_capabilities: HclControlCapabilities
    must_not_exist: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=5))

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value, label="topology plan timestamps")

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")

        if self.operations != canonical_topology_operations(self.desired_topology):
            raise ValueError("operations must match the canonical isolated-project plan")
        expected_risk = RiskLevel.R2 if self.desired_topology.devices else RiskLevel.R1
        if self.risk_level != expected_risk:
            raise ValueError("risk_level does not match topology operations")
        if self.estimate.device_count != len(self.desired_topology.devices):
            raise ValueError("device estimate does not match desired topology")
        if self.estimate.link_count != len(self.desired_topology.links):
            raise ValueError("link estimate does not match desired topology")
        expected_concurrency = min(
            len(self.desired_topology.devices),
            self.budget.max_concurrent_starts,
        )
        if self.estimate.concurrent_starts != expected_concurrency:
            raise ValueError("start concurrency estimate does not match the plan")

        required_kinds = {operation.kind for operation in self.operations}
        missing_kinds = sorted(
            kind.value for kind in required_kinds if not self.provider_capabilities.supports(kind)
        )
        if missing_kinds:
            raise ValueError("provider capabilities do not cover plan operations")
        if any(
            not self.provider_capabilities.supports_model(device.model)
            for device in self.desired_topology.devices
        ):
            raise ValueError("provider capabilities do not cover plan models")

        checks = (
            ("devices", self.estimate.device_count, self.budget.max_devices),
            ("links", self.estimate.link_count, self.budget.max_links),
            ("concurrent_starts", self.estimate.concurrent_starts, self.budget.max_concurrent_starts),
            ("estimated_memory_mb", self.estimate.estimated_memory_mb, self.budget.max_estimated_memory_mb),
            ("estimated_total_seconds", self.estimate.estimated_total_seconds, self.budget.max_total_seconds),
        )
        for resource_name, estimate, limit in checks:
            if estimate > limit:
                raise ValueError(f"resource estimate exceeds budget: {resource_name}")

        expected_hash = topology_plan_content_hash(
            risk_level=self.risk_level,
            desired_topology=self.desired_topology,
            operations=self.operations,
            budget=self.budget,
            estimate=self.estimate,
            provider_capabilities=self.provider_capabilities,
            must_not_exist=self.must_not_exist,
        )
        if self.content_hash != expected_hash:
            raise ValueError("content_hash does not match topology plan content")
        return self

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def revalidate_for_execution(self) -> Self:
        """Reconstruct the model to catch unsafe ``model_copy`` mutations."""

        validated = type(self).model_validate(self.model_dump(mode="python"))
        if validated.is_expired:
            raise DomainError(ErrorCode.PLAN_EXPIRED, "Topology plan has expired")
        return validated


class TopologySnapshot(BaseModel):
    """Immutable topology and runtime baseline captured before side effects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: str = Field(min_length=1, max_length=128)
    topology: DesiredTopology
    baseline_hash: str = Field(pattern=_HASH_PATTERN)
    captured_at: datetime
    running_device_logical_ids: tuple[str, ...] = ()

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        return _canonical_windows_name(value, label="project name")

    @field_validator("captured_at")
    @classmethod
    def require_aware_captured_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, label="captured_at")

    @field_validator("running_device_logical_ids")
    @classmethod
    def canonicalize_running_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.lower() for item in value)
        if any(not item or len(item) > 128 for item in normalized):
            raise ValueError("running device logical IDs must be bounded")
        return normalized

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if _windows_identity(self.project_name) != _windows_identity(self.topology.project_name):
            raise ValueError("snapshot project_name must match topology project_name")
        if len(self.running_device_logical_ids) != len(set(self.running_device_logical_ids)):
            raise ValueError("running device logical IDs must be unique")
        known_devices = {device.logical_id for device in self.topology.devices}
        for logical_id in self.running_device_logical_ids:
            if logical_id not in known_devices:
                raise ValueError(f"running device does not exist in topology: {logical_id}")
        object.__setattr__(self, "running_device_logical_ids", tuple(sorted(self.running_device_logical_ids)))
        return self


class OperationContext(BaseModel):
    """Plan-, grant-, baseline-, and fence-bound Provider call context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    execution_grant_id: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    project_name: str = Field(min_length=1, max_length=128)
    plan_id: str = Field(min_length=1, max_length=128, pattern=_OPAQUE_ID_PATTERN)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    expected_baseline_hash: str = Field(pattern=_HASH_PATTERN)
    operation_index: int = Field(ge=0)
    operation_digest: str = Field(pattern=_HASH_PATTERN)
    fencing_token: int = Field(gt=0)
    issued_at: datetime
    deadline: datetime

    @field_validator("project_name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        return _canonical_windows_name(value, label="project name")

    @field_validator("issued_at", "deadline")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, label="operation context timestamps")

    @model_validator(mode="after")
    def validate_deadline(self) -> Self:
        if self.deadline <= self.issued_at:
            raise ValueError("deadline must be later than issued_at")
        return self

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.deadline


class OperationReceipt(BaseModel):
    """Bounded Provider receipt that cannot carry paths or free-form text."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    kind: TopologyOperationKind
    context: OperationContext
    operation_digest: str = Field(pattern=_HASH_PATTERN)
    changed: bool
    checkpoint_hash: str = Field(pattern=_HASH_PATTERN)
    completed_at: datetime
    warning_codes: tuple[str, ...] = ()

    @field_validator("completed_at")
    @classmethod
    def require_aware_completed_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, label="completed_at")

    @field_validator("warning_codes")
    @classmethod
    def validate_warning_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(code) > 64
            or not code
            or not code[0].isalpha()
            or not all(char.isupper() or char.isdigit() or char == "_" for char in code)
            for code in value
        ):
            raise ValueError("warning_codes must contain safe symbolic codes")
        if len(value) != len(set(value)):
            raise ValueError("warning_codes must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_receipt_binding(self) -> Self:
        if self.operation_digest != self.context.operation_digest:
            raise ValueError("receipt operation digest does not match its context")
        if self.completed_at < self.context.issued_at or self.completed_at > self.context.deadline:
            raise ValueError("receipt completion time is outside the operation context")
        return self
