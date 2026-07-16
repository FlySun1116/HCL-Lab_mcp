"""HCL project repository — discover and parse local HCL project files.

Implements the ProjectRepository port using filesystem scanning and JSON/configparser.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from h3c_hcl_mcp.adapters.hcl.net_parser import parse_net_file
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import DeviceRef, LabProject, Link, Topology
from h3c_hcl_mcp.ports.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


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


def _read_project_json(project_dir: str) -> dict[str, object]:
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

    # Normalize to internal format — supports both:
    # 1. Real HCL 5.10.3: {"projectInfo": {...}, "deviceInfoList": [...]}
    # 2. Synthetic/test:  {"id": "...", "name": "...", "devices": [...]}
    fallback_id = os.path.basename(os.path.normpath(project_dir))
    data = _normalize_project_json(data, json_path, fallback_id=fallback_id)

    if "id" not in data:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="project.json missing required project identifier",
            details={"path": json_path},
        )

    return data


def _normalize_project_json(
    data: dict[str, object], json_path: str, fallback_id: str = ""
) -> dict[str, object]:
    """Normalize project.json to internal format.

    Detects and converts the real HCL 5.10.3 schema:
      {"projectInfo": {"name": ..., "path": ..., "visibility": ...},
       "deviceInfoList": [{"resourceName": ..., "resourceCategory": ..., ...}]}
    into the internal schema:
      {"id": ..., "name": ..., "version": ..., "devices": [...]}

    REAL field priority (HCL 5.10.3) always checked FIRST:
      projectInfo.name, projectInfo.path, projectInfo.visibility
      deviceInfoList[].resourceName, resourceCategory, resourceModel,
      resourceVersion, configPath

    Backward compatible with old synthetic format and v1 guessed names.
    """
    if "projectInfo" in data or "deviceInfoList" in data:
        info = data.get("projectInfo", {})
        if isinstance(info, dict):
            # REAL field names FIRST (HCL 5.10.3), then guessed, then synthetic
            project_id = str(
                info.get("path")
                or info.get("projectId")
                or info.get("id")
                or fallback_id
                or ""
            )
            normalized: dict[str, object] = {
                "id": project_id,
                "name": str(
                    info.get("name")
                    or info.get("projectName")
                    or "Unknown"
                ),
                "version": str(info.get("hclVersion") or info.get("version") or ""),
            }
        else:
            normalized = {"id": fallback_id or "", "name": "Unknown", "version": ""}

        device_list = data.get("deviceInfoList", data.get("devices", []))
        if isinstance(device_list, list):
            devices = []
            for d in device_list:
                if not isinstance(d, dict):
                    continue
                # REAL field names FIRST (HCL 5.10.3 resourceName etc.)
                # deviceId: real HCL 5.10.3 deviceInfoList has NO deviceId.
                # Use -1 as sentinel; caller must resolve from .net via
                # resourceName matching.
                raw_id = d.get("deviceId", d.get("id"))
                device_id = int(str(raw_id)) if raw_id is not None else -1
                devices.append({
                    "name": str(
                        d.get("resourceName")
                        or d.get("deviceName")
                        or d.get("name")
                        or ""
                    ),
                    "id": device_id,
                    "model": str(
                        d.get("resourceModel")
                        or d.get("deviceModel")
                        or d.get("model")
                        or ""
                    ),
                    "category": str(
                        d.get("resourceCategory")
                        or d.get("deviceType")
                        or d.get("category")
                        or ""
                    ),
                    "version": str(
                        d.get("resourceVersion")
                        or d.get("comwareVersion")
                        or d.get("version")
                        or ""
                    ),
                    "configPath": str(d.get("configPath", "")),
                })
            normalized["devices"] = devices
        else:
            normalized["devices"] = []

        return normalized

    # Already in internal/synthetic format — pass through
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
                    except DomainError as e:
                        # Collect skipped project info for diagnostics
                        logger.debug("Skipping %s: %s", entry.name, e.message)
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

            name = str(data.get("name", project_id))
            hcl_version_raw = data.get("version")
            hcl_version = str(hcl_version_raw) if hcl_version_raw is not None else None
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

        # Build name→device map from project.json
        json_by_name: dict[str, dict[str, object]] = {}
        json_by_id: dict[int, dict[str, object]] = {}
        for d in json_devices:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name", ""))
            raw_id = d.get("id")
            did = int(str(raw_id)) if raw_id is not None else -1
            if name:
                json_by_name[name] = d
            if did > 0:
                json_by_id[did] = d
            elif name:
                json_by_id[-1] = d  # sentinel for name-only resolution

        # Parse .net file FIRST for authoritative device IDs and names
        net_file = _find_net_file(project_dir)
        warnings: list[str] = []
        net_devices_list: list = []
        links: list[Link] = []

        if net_file is not None:
            net_devices_list, net_links_list = parse_net_file(net_file)
            for nl in net_links_list:
                links.append(nl.to_domain_link())

        # Build device refs, resolving IDs from .net via resourceName matching
        device_refs: dict[int, DeviceRef] = {}
        net_name_to_id = {nd.name: nd.device_id for nd in net_devices_list}
        net_id_to_net_dev = {nd.device_id: nd for nd in net_devices_list}

        for d in json_devices:
            if not isinstance(d, dict):
                continue
            device_name = str(d.get("name", ""))
            raw_id = d.get("id")
            did = int(str(raw_id)) if raw_id is not None else -1

            # Resolve device ID: .net is authoritative when available
            if did <= 0 and device_name and device_name in net_name_to_id:
                did = net_name_to_id[device_name]
            elif did <= 0:
                warnings.append(
                    f"Device {device_name!r} has no device_id and not found in .net"
                )
                continue  # skip devices we can't identify

            device_refs[did] = DeviceRef(
                project_id=project_id,
                device_id=did,
                name=device_name,
                model=str(d.get("model", "")),
                comware_version=str(d.get("version", "")),
                config_path=str(d.get("configPath", "")),
                category=str(d.get("category", "")),
            )

        # Add .net-only devices not in project.json
        for nd in net_devices_list:
            if nd.device_id not in device_refs:
                device_refs[nd.device_id] = DeviceRef(
                    project_id=project_id,
                    device_id=nd.device_id,
                    name=nd.name,
                    model=nd.model or "",
                    category=nd.device_type or "",
                )
                warnings.append(
                    f"Device {nd.name!r} (id={nd.device_id}) in .net but not in project.json"
                )

        if not device_refs:
            warnings.append("No identifiable devices found in project")

        if net_file is None:
            warnings.append("No .net topology file found; device IDs from project.json only")

        return Topology(
            project_id=project_id,
            devices=list(device_refs.values()),
            links=links,
            warnings=warnings,
        )
