"""Port: ProjectRepository — discover and read HCL projects."""

from __future__ import annotations

from abc import ABC, abstractmethod

from h3c_hcl_mcp.domain.project import LabProject, Topology


class ProjectRepository(ABC):
    """Read-only access to local HCL project metadata and topology.

    Implementations may parse HCL project directories, read project.json/.net files,
    or use future official HCL APIs.
    """

    @abstractmethod
    async def list_projects(
        self,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[LabProject], str | None]:
        """List discovered HCL projects, with optional cursor-based pagination.

        Returns (projects, next_cursor). next_cursor is None when there are no more pages.
        """
        ...

    @abstractmethod
    async def get_project(self, project_id: str) -> LabProject:
        """Get a single project by ID.

        Raises:
            DomainError(PROJECT_NOT_FOUND): project does not exist.
        """
        ...

    @abstractmethod
    async def get_topology(
        self,
        project_id: str,
        include_positions: bool = False,
    ) -> Topology:
        """Get full topology (devices, links) for a project.

        Args:
            project_id: Project identifier.
            include_positions: Whether to include UI layout coordinates.

        Raises:
            DomainError(PROJECT_NOT_FOUND): project does not exist.
            DomainError(PROJECT_DAMAGED): project files are corrupted.
        """
        ...
