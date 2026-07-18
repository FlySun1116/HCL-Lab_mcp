"""Contract tests for Port interfaces — verify they can be implemented."""

import abc
import inspect

import pytest

from h3c_hcl_mcp.ports.approval_provider import ApprovalProvider
from h3c_hcl_mcp.ports.audit_sink import AuditSink
from h3c_hcl_mcp.ports.command_parser import CommandParser
from h3c_hcl_mcp.ports.device_transport import DeviceTransport
from h3c_hcl_mcp.ports.hcl_control_provider import HclControlProvider
from h3c_hcl_mcp.ports.job_store import JobStore
from h3c_hcl_mcp.ports.policy_engine import PolicyEngine
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery
from h3c_hcl_mcp.ports.secret_provider import SecretProvider

ALL_PORTS = [
    ProjectRepository,
    RuntimeDiscovery,
    DeviceTransport,
    CommandParser,
    PolicyEngine,
    ApprovalProvider,
    AuditSink,
    JobStore,
    SecretProvider,
    HclControlProvider,
]


class TestAllPortsAreABC:
    """Every port must be an ABC so it cannot be instantiated directly."""

    @pytest.mark.parametrize("port_cls", ALL_PORTS)
    def test_is_abstract(self, port_cls):
        assert abc.ABC in port_cls.__mro__ or hasattr(port_cls, "__abstractmethods__"), (
            f"{port_cls.__name__} must be abstract"
        )

    @pytest.mark.parametrize("port_cls", ALL_PORTS)
    def test_cannot_instantiate_directly(self, port_cls):
        with pytest.raises(TypeError):
            port_cls()  # type: ignore


class TestPortMethodsAreAbstract:
    """Every public method on a Port should be abstract."""

    @pytest.mark.parametrize("port_cls", ALL_PORTS)
    def test_all_methods_abstract(self, port_cls):
        methods = inspect.getmembers(port_cls, predicate=inspect.isfunction)
        for name, method in methods:
            if name.startswith("_") or name == "__init__":
                continue
            assert hasattr(method, "__isabstractmethod__"), (
                f"{port_cls.__name__}.{name}() must be @abstractmethod"
            )


class TestPortOnlyDependOnDomain:
    """Port methods should use domain types in their signatures, not adapter or MCP types."""

    def test_project_repository_uses_domain_types(self):
        src = inspect.getsource(ProjectRepository.list_projects)
        assert "LabProject" in src

    def test_runtime_discovery_uses_domain_types(self):
        src = inspect.getsource(RuntimeDiscovery.discover_project)
        assert "DeviceRuntime" in src

    def test_device_transport_uses_domain_types(self):
        src = inspect.getsource(DeviceTransport.execute)
        assert "CommandResult" in src

    def test_hcl_control_provider_uses_only_typed_domain_contracts(self):
        source = inspect.getsource(HclControlProvider)
        assert "dict[" not in source
        assert "Any" not in source
        assert "HclControlCapabilities" in source
        assert "TopologySnapshot" in source
        assert "TopologyOperation" in source
        assert "OperationContext" in source
        assert "OperationReceipt" in source


class TestHclControlProviderContract:
    def test_has_only_three_public_methods(self):
        methods = {
            name
            for name, method in inspect.getmembers(HclControlProvider, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert methods == {"capabilities", "snapshot", "apply_operation"}

    @pytest.mark.parametrize(
        ("method_name", "parameter_names", "return_annotation"),
        [
            ("capabilities", ["self"], "HclControlCapabilities"),
            ("snapshot", ["self", "project_name"], "TopologySnapshot"),
            (
                "apply_operation",
                ["self", "operation", "context"],
                "OperationReceipt",
            ),
        ],
    )
    def test_method_signatures(
        self,
        method_name: str,
        parameter_names: list[str],
        return_annotation: str,
    ):
        signature = inspect.signature(getattr(HclControlProvider, method_name))
        assert list(signature.parameters) == parameter_names
        assert signature.return_annotation == return_annotation

    def test_parameter_annotations_are_typed(self):
        snapshot_signature = inspect.signature(HclControlProvider.snapshot)
        apply_signature = inspect.signature(HclControlProvider.apply_operation)

        assert snapshot_signature.parameters["project_name"].annotation == "str"
        assert apply_signature.parameters["operation"].annotation == "TopologyOperation"
        assert apply_signature.parameters["context"].annotation == "OperationContext"
