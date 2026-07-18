"""Port for an authorized HCL topology-control provider."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3c_hcl_mcp.domain.topology_control import (
    HclControlCapabilities,
    OperationContext,
    OperationReceipt,
    TopologyOperation,
    TopologySnapshot,
)


class HclControlProvider(ABC):
    """Execute structured HCL operations through an authorized provider."""

    @abstractmethod
    async def capabilities(self) -> HclControlCapabilities:
        """Return the provider and HCL versions plus supported operations."""

        ...

    @abstractmethod
    async def snapshot(self, project_name: str) -> TopologySnapshot:
        """Capture a topology and runtime baseline for a named project."""

        ...

    @abstractmethod
    async def apply_operation(
        self,
        operation: TopologyOperation,
        context: OperationContext,
    ) -> OperationReceipt:
        """Apply one structured operation under plan/grant/baseline fencing.

        Implementations must reject expired contexts, mismatched operation
        digests, stale fencing tokens, baseline changes, and a CREATE_PROJECT
        whose target already exists.  Receipts must echo the complete context
        and contain only hashes and symbolic warning codes.
        """

        ...
