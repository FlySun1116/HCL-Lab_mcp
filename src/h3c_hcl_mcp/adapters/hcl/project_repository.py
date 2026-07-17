"""HCL project repository — discover and parse local HCL project files.

Implements the ProjectRepository port using filesystem scanning and JSON/configparser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ntpath
import os
import re
from datetime import UTC, datetime

from h3c_hcl_mcp.adapters.hcl.net_parser import (
    NetDeviceEntry,
    _validate_net_file_size,
    parse_net_file,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import DeviceRef, LabProject, Link, Topology
from h3c_hcl_mcp.ports.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


# project.json contains only project metadata and device descriptors.  Sixteen
# MiB accommodates large HCL labs without allowing an untrusted project to
# trigger an unbounded JSON read.
MAX_PROJECT_JSON_BYTES = 16 * 1024 * 1024


def _validate_project_path(project_dir: str) -> None:
    """Reject explicit parent traversal without exposing the configured root.

    Raises:
        DomainError(PROJECT_PATH_TRAVERSAL): path contains a parent component.
    """
    if ".." in re.split(r"[\\/]", project_dir):
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message="Path traversal detected in project path",
        )


def _validate_project_id(project_id: str) -> None:
    """Require a single HCL project directory name, never a filesystem path."""
    if (
        not project_id
        or project_id in {".", ".."}
        or os.path.basename(project_id) != project_id
        or ntpath.basename(project_id) != project_id
        or os.path.isabs(project_id)
        or ntpath.isabs(project_id)
    ):
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message="Project identifier must be a directory name",
            details={"project_id": project_id},
        )


def _resolve_project_dir(projects_dir: str, project_id: str) -> str:
    """Resolve a project below its configured root, including symlink checks."""
    _validate_project_id(project_id)
    root = os.path.realpath(os.path.abspath(projects_dir))
    candidate = os.path.realpath(os.path.join(root, project_id))
    try:
        inside_root = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message="Project directory is outside the configured root",
            details={"project_id": project_id},
        )
    return candidate


def _resolve_project_reference(project_dir: str, reference: str, *, label: str) -> str:
    """Resolve an untrusted metadata file reference below ``project_dir``.

    HCL emits Windows-style relative paths even when tests run elsewhere, so
    both slash styles are normalized.  ``realpath``/``commonpath`` also reject
    existing symlink and Windows junction escapes.
    """
    raw_reference = reference.strip()
    if not raw_reference or "\x00" in raw_reference:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Invalid {label} reference",
            details={"file": label},
        )
    if (
        raw_reference.startswith(("/", "\\"))
        or os.path.isabs(raw_reference)
        or ntpath.isabs(raw_reference)
        or bool(ntpath.splitdrive(raw_reference)[0])
    ):
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Absolute {label} reference is not allowed",
            details={"file": label},
        )

    raw_parts = re.split(r"[\\/]", raw_reference)
    if any(part == ".." or ":" in part for part in raw_parts):
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Unsafe {label} reference is not allowed",
            details={"file": label},
        )
    parts = [part for part in raw_parts if part not in {"", "."}]
    if not parts:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Invalid {label} reference",
            details={"file": label},
        )

    root = os.path.realpath(os.path.abspath(project_dir))
    candidate = os.path.realpath(os.path.abspath(os.path.join(root, *parts)))
    try:
        inside_project = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside_project = False
    if not inside_project:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"{label.capitalize()} reference is outside the project",
            details={"file": label},
        )
    return candidate


def _validate_metadata_references(data: dict[str, object], project_dir: str) -> None:
    """Validate every file reference exposed by normalized project metadata."""
    devices = data.get("devices", [])
    if not isinstance(devices, list):
        return
    for device in devices:
        if not isinstance(device, dict):
            continue
        config_path = str(device.get("configPath") or "").strip()
        if config_path:
            _resolve_project_reference(project_dir, config_path, label="config snapshot")


def _read_project_json(project_dir: str) -> dict[str, object]:
    """Read and parse project.json from a project directory.

    Raises:
        DomainError(PROJECT_NOT_FOUND): project.json does not exist.
        DomainError(PROJECT_DAMAGED): project.json is invalid JSON.
    """
    _validate_project_path(project_dir)

    json_path = _resolve_project_reference(project_dir, "project.json", label="project.json")
    if not os.path.isfile(json_path):
        raise DomainError(
            code=ErrorCode.PROJECT_NOT_FOUND,
            message="project.json not found",
            details={"file": "project.json"},
        )

    try:
        size = os.path.getsize(json_path)
        if size > MAX_PROJECT_JSON_BYTES:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message="project.json exceeds the supported size limit",
                details={"file": "project.json", "max_bytes": MAX_PROJECT_JSON_BYTES},
            )
        with open(json_path, "rb") as file:
            raw = file.read(MAX_PROJECT_JSON_BYTES + 1)
        if len(raw) > MAX_PROJECT_JSON_BYTES:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message="project.json exceeds the supported size limit",
                details={"file": "project.json", "max_bytes": MAX_PROJECT_JSON_BYTES},
            )
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Invalid JSON in project.json: {e}",
            details={"file": "project.json"},
        ) from e
    except (OSError, UnicodeError) as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="Cannot read project.json",
            details={"file": "project.json"},
        ) from e

    # Basic structural validation
    if not isinstance(data, dict):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="project.json must contain a JSON object",
            details={"file": "project.json"},
        )

    # Normalize to internal format — supports both:
    # 1. Real HCL 5.10.3: {"projectInfo": {...}, "deviceInfoList": [...]}
    # 2. Synthetic/test:  {"id": "...", "name": "...", "devices": [...]}
    fallback_id = os.path.basename(os.path.normpath(project_dir))
    data = _normalize_project_json(data, "project.json", fallback_id=fallback_id)

    if "id" not in data:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="project.json missing required project identifier",
            details={"file": "project.json"},
        )

    _validate_metadata_references(data, project_dir)
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
            # The directory is the stable identifier used by HCL itself.  Some
            # projects contain an absolute or stale projectInfo.path after they
            # have been copied, so it must not make an otherwise valid project
            # undiscoverable.
            info_path = str(info.get("path") or "")
            path_id = os.path.basename(os.path.normpath(info_path)) if info_path else ""
            project_id = str(fallback_id or path_id or info.get("projectId") or info.get("id") or "")
            normalized: dict[str, object] = {
                "id": project_id,
                "name": str(info.get("name") or info.get("projectName") or "Unknown"),
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
                devices.append(
                    {
                        "name": str(d.get("resourceName") or d.get("deviceName") or d.get("name") or ""),
                        "id": device_id,
                        "model": str(d.get("resourceModel") or d.get("deviceModel") or d.get("model") or ""),
                        "category": str(
                            d.get("resourceCategory") or d.get("deviceType") or d.get("category") or ""
                        ),
                        "version": str(
                            d.get("resourceVersion") or d.get("comwareVersion") or d.get("version") or ""
                        ),
                        "configPath": str(d.get("configPath", "")),
                    }
                )
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
        with os.scandir(project_dir) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.endswith(".net"):
                    return _resolve_project_reference(project_dir, entry.name, label=".net topology")
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


def _read_net_version(project_dir: str) -> str | None:
    """Read the public HCL version header without parsing the full topology."""
    net_file = _find_net_file(project_dir)
    if net_file is None:
        return None
    _validate_net_file_size(net_file)
    try:
        with open(net_file, encoding="utf-8-sig") as file:
            for _ in range(10):
                line = file.readline(4096)
                if not line:
                    break
                match = re.match(r"^\s*version\s*=\s*(\S+)\s*$", line, re.IGNORECASE)
                if match:
                    return match.group(1)
    except (OSError, UnicodeError):
        return None
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
        return await asyncio.to_thread(self._list_projects_sync, query, limit, cursor)

    def _list_projects_sync(
        self,
        query: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[LabProject], str | None]:
        """Blocking project scan executed outside the MCP event loop."""
        all_projects: list[LabProject] = []

        for projects_dir in self._projects_dirs:
            _validate_project_path(projects_dir)

            if not os.path.isdir(projects_dir):
                continue

            try:
                with os.scandir(projects_dir) as entries:
                    for entry in entries:
                        if not entry.is_dir():
                            continue

                        try:
                            project = self._get_project_sync(entry.name)
                            all_projects.append(project)
                        except DomainError as e:
                            # Collect skipped project info for diagnostics
                            logger.debug("Skipping unreadable project entry: %s", e.code.value)
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
        return await asyncio.to_thread(self._get_project_sync, project_id)

    def _get_project_sync(self, project_id: str) -> LabProject:
        """Blocking project lookup executed outside the MCP event loop."""
        _validate_project_id(project_id)
        for projects_dir in self._projects_dirs:
            _validate_project_path(projects_dir)
            project_dir = _resolve_project_dir(projects_dir, project_id)

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
            hcl_version = str(hcl_version_raw or "").strip() or _read_net_version(project_dir)
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
        return await asyncio.to_thread(self._get_topology_sync, project_id, include_positions)

    def _get_topology_sync(
        self,
        project_id: str,
        include_positions: bool = False,
    ) -> Topology:
        """Blocking topology parse executed outside the MCP event loop."""
        del include_positions  # positions are not exposed by HCL 5.10 project files
        # First, verify the project exists
        lab_project = self._get_project_sync(project_id)
        project_dir = lab_project.path

        # Read project.json for device list
        data = _read_project_json(project_dir)
        json_devices = data.get("devices", [])

        if not isinstance(json_devices, list):
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message="project.json 'devices' field must be an array",
                details={"file": "project.json"},
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
        net_devices_list: list[NetDeviceEntry] = []
        links: list[Link] = []

        if net_file is not None:
            net_devices_list, net_links_list = parse_net_file(net_file)
            for nl in net_links_list:
                links.append(nl.to_domain_link())

        # Build device refs, resolving IDs from .net via resourceName matching
        device_refs: dict[int, DeviceRef] = {}
        net_name_to_id = {nd.name: nd.device_id for nd in net_devices_list}
        net_name_to_id_folded = {nd.name.casefold(): nd.device_id for nd in net_devices_list}
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
            elif did <= 0 and device_name.casefold() in net_name_to_id_folded:
                did = net_name_to_id_folded[device_name.casefold()]
            elif did <= 0:
                warnings.append(f"Device {device_name!r} has no device_id and not found in .net")
                continue  # skip devices we can't identify

            net_device = net_id_to_net_dev.get(did)
            canonical_name = net_device.name if net_device is not None else device_name
            device_refs[did] = DeviceRef(
                project_id=project_id,
                device_id=did,
                name=canonical_name,
                model=str(d.get("model", "")) or (net_device.model if net_device else ""),
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
                warnings.append(f"Device {nd.name!r} (id={nd.device_id}) in .net but not in project.json")

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
