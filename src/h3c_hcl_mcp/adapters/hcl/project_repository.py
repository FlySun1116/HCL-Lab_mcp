"""HCL project repository — discover and parse local HCL project files.

Implements the ProjectRepository port using filesystem scanning and JSON/configparser.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from h3c_hcl_mcp.adapters.hcl.net_parser import parse_net_file
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import DeviceRef, LabProject, Link, Topology
from h3c_hcl_mcp.ports.project_repository import ProjectRepository


def _validate_project_path(project_dir: str) -> None:
    """Validate that a project directory path is safe.

    Raises:
        DomainError(PROJECT_PATH_TRAVERSAL): path contains traversal or is absolute.
    """
    if ".." in project_dir:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Path traversal detected in project path: {project_dir!r}",
            details={"path": project_dir},
        )


def _read_project_json(project_dir: str) -> dict:
    """Read and parse project.json from a project directory.

    Raises:
        DomainError(PROJECT_NOT_FOUND): project.json does not exist.
        DomainError(PROJECT_DAMAGED): project.json is invalid JSON.
    """
    _validate_project_path(project_dir)

    json_path = os.path.join(project_dir, "project.json")
    if not os.path.isfile(json_path):
        raise DomainError(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message=f"project.json not found in {project_dir!r}",
            details={"path": json_path},
        )

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Invalid JSON in project.json: {e}",
            details={"path": json_path},
        ) from e
    except OSError as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Cannot read project.json: {e}",
            details={"path": json_path},
        ) from e

    # Basic structural validation
    if not isinstance(data, dict):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="project.json must contain a JSON object",
            details={"path": json_path},
        )

    if "id" not in data:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="project.json missing required field 'id'",
            details={"path": json_path},
        )

    return data


def _find_net_file(project_dir: str) -> str | None:
    """Find the .net topology file in a project directory.

    Returns the absolute path to the .net file, or None if not found.
    """
    _validate_project_path(project_dir)

    try:
        for entry in os.scandir(project_dir):
            if entry.is_file() and entry.name.endswith(".net"):
                return entry.path
    except OSError:
        pass

    return None


def _get_file_mtime(file_path: str) -> datetime | None:
    """Get the modification time of a file as a UTC datetime."""
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime, tz=UTC)
    except OSError:
        return None


class HCLProjectRepository(ProjectRepository):
    """Filesystem-backed HCL project repository.

    Scans configured directories for project.json files and parses
    associated .net topology files.

    Args:
        projects_dirs: List of directories to scan for HCL projects.
    """

    def __init__(self, projects_dirs: list[str] | None = None) -> None:
        self._projects_dirs: list[str] = projects_dirs or []

    @property
    def projects_dirs(self) -> list[str]:
        return list(self._projects_dirs)

    def add_projects_dir(self, directory: str) -> None:
        """Add a directory to scan for HCL projects."""
        _validate_project_path(directory)
        if directory not in self._projects_dirs:
            self._projects_dirs.append(directory)

    async def list_projects(
        self,
        query: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[LabProject], str | None]:
        """List discovered HCL projects across all configured directories.

        Returns (projects, next_cursor). next_cursor is None when there are no more pages.
        """
        all_projects: list[LabProject] = []

        for projects_dir in self._projects_dirs:
            _validate_project_path(projects_dir)

            if not os.path.isdir(projects_dir):
                continue

            try:
                for entry in os.scandir(projects_dir):
                    if not entry.is_dir():
                        continue

                    try:
                        project = await self.get_project(entry.name)
                        all_projects.append(project)
                    except DomainError:
                        # Skip directories that don't contain valid HCL projects
                        continue
            except OSError:
                continue

        # Apply query filter
        if query:
            query_lower = query.lower()
            all_projects = [
                p
                for p in all_projects
                if query_lower in p.name.lower() or query_lower in p.project_id.lower()
            ]

        # Sort by name for stable output
        all_projects.sort(key=lambda p: p.name)

        # Apply cursor-based pagination
        total = len(all_projects)
        start_idx = 0
        if cursor:
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                start_idx = 0

        end_idx = min(start_idx + limit, total)
        page = all_projects[start_idx:end_idx]
        next_cursor = str(end_idx) if end_idx < total else None

        return page, next_cursor

    async def get_project(self, project_id: str) -> LabProject:
        """Get a single project by its directory name (project_id).

        Scans all configured projects_dirs for a directory matching project_id.
        """
        for projects_dir in self._projects_dirs:
            _validate_project_path(projects_dir)
            project_dir = os.path.join(projects_dir, project_id)

            if not os.path.isdir(project_dir):
                continue

            try:
                data = _read_project_json(project_dir)
            except DomainError as e:
                if e.code == ErrorCode.PROJECT_NOT_FOUND:
                    continue
                raise

            # Verify the project.json id matches the directory
            json_id = data.get("id", "")
            if json_id != project_id:
                continue

            name = data.get("name", project_id)
            hcl_version = data.get("version")
            devices = data.get("devices", [])
            device_count = len(devices) if isinstance(devices, list) else 0

            json_path = os.path.join(project_dir, "project.json")
            updated_at = _get_file_mtime(json_path)

            return LabProject(
                project_id=project_id,
                name=name,
                path=project_dir,
                hcl_version=hcl_version,
                device_count=device_count,
                updated_at=updated_at,
            )

        raise DomainError(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message=f"Project not found: {project_id!r}",
            details={"project_id": project_id},
        )

    async def get_topology(
        self,
        project_id: str,
        include_positions: bool = False,
    ) -> Topology:
        """Get full topology (devices, links) for a project.

        Combines data from project.json and .net file, cross-validating
        that devices appear in both.
        """
        # First, verify the project exists
        lab_project = await self.get_project(project_id)
        project_dir = lab_project.path

        # Read project.json for device list
        data = _read_project_json(project_dir)
        json_devices = data.get("devices", [])

        if not isinstance(json_devices, list):
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message="project.json 'devices' field must be an array",
                details={"path": os.path.join(project_dir, "project.json")},
            )

        # Build device refs from project.json
        device_refs: dict[int, DeviceRef] = {}
        for d in json_devices:
            if not isinstance(d, dict):
                continue
            device_id = d.get("id")
            if device_id is None:
                continue
            device_id = int(device_id)
            device_refs[device_id] = DeviceRef(
                project_id=project_id,
                device_id=device_id,
                name=str(d.get("name", f"Device_{device_id}")),
                model=d.get("model"),
                comware_version=d.get("version"),
                config_path=d.get("configPath"),
                category=d.get("category"),
            )

        # Parse .net file for topology links
        net_file = _find_net_file(project_dir)
        if net_file is None:
            # No .net file — return topology with devices only
            return Topology(
                project_id=project_id,
                devices=list(device_refs.values()),
                links=[],
                warnings=["No .net topology file found"],
            )

        net_devices, net_links = parse_net_file(net_file)

        # Cross-validate: devices in project.json must match devices in .net
        net_device_ids = {d.device_id for d in net_devices}
        json_device_ids = set(device_refs.keys())

        warnings: list[str] = []

        # Devices in .net but not in project.json
        for nd in net_devices:
            if nd.device_id not in json_device_ids:
                warnings.append(
                    f"Device {nd.name!r} (id={nd.device_id}) found in .net but not in project.json"
                )

        # Devices in project.json but not in .net
        for did in json_device_ids - net_device_ids:
            dr = device_refs[did]
            warnings.append(f"Device {dr.name!r} (id={did}) found in project.json but not in .net")

        # Build domain links, preserving net device info for DeviceRef
        links: list[Link] = []
        for nl in net_links:
            links.append(nl.to_domain_link())

        # Validate links reference known devices
        known_ids = json_device_ids | net_device_ids
        for nl in net_links:
            if nl.local_device not in known_ids:
                warnings.append(f"Link references unknown local device {nl.local_device}")
            if nl.remote_device not in known_ids:
                warnings.append(f"Link references unknown remote device {nl.remote_device}")

        # Merge device refs: prefer project.json, supplement from .net
        devices = list(device_refs.values())
        for nd in net_devices:
            if nd.device_id not in device_refs:
                # Device only in .net — create a DeviceRef from net data
                devices.append(
                    DeviceRef(
                        project_id=project_id,
                        device_id=nd.device_id,
                        name=nd.name,
                        model=nd.model,
                        category=nd.device_type,
                    )
                )

        return Topology(
            project_id=project_id,
            devices=devices,
            links=links,
            warnings=warnings,
        )
