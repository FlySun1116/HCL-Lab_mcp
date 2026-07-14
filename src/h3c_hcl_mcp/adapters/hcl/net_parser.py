"""Parser for HCL .net topology files using configparser.

The .net file is an INI-style file that describes the topology:
devices, their positions, and links between interfaces.
"""

from __future__ import annotations

import configparser
import os
from typing import Any

from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.domain.project import Link


class NetDeviceEntry:
    """Parsed device entry from a .net file."""

    def __init__(
        self,
        name: str,
        device_id: int,
        device_type: str | None = None,
        model: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        self.name = name
        self.device_id = device_id
        self.device_type = device_type
        self.model = model
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return f"NetDeviceEntry(id={self.device_id}, name={self.name!r})"


class NetLinkEntry:
    """Parsed link entry from a .net file."""

    def __init__(
        self,
        local_device: int,
        local_if: str,
        local_port: int | None,
        remote_device: int,
        remote_if: str,
        remote_port: int | None,
    ) -> None:
        self.local_device = local_device
        self.local_if = local_if
        self.local_port = local_port
        self.remote_device = remote_device
        self.remote_if = remote_if
        self.remote_port = remote_port

    def to_domain_link(self) -> Link:
        return Link(
            local_device_id=self.local_device,
            local_interface=self.local_if,
            remote_device_id=self.remote_device,
            remote_interface=self.remote_if,
            link_type="ethernet",
        )

    def __repr__(self) -> str:
        return f"NetLinkEntry({self.local_device}:{self.local_if} -> {self.remote_device}:{self.remote_if})"


def _validate_path(file_path: str) -> None:
    """Reject path traversal patterns.

    Raises:
        DomainError(PROJECT_PATH_TRAVERSAL): if the path contains traversal patterns.
    """
    # Reject path traversal patterns (.. anywhere in path)
    if ".." in file_path:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Path traversal detected: {file_path!r}",
            details={"path": file_path},
        )


def parse_net_file(file_path: str) -> tuple[list[NetDeviceEntry], list[NetLinkEntry]]:
    """Parse an HCL .net topology file.

    Args:
        file_path: Absolute path to the .net file.

    Returns:
        Tuple of (devices, links) parsed from the file.

    Raises:
        DomainError(PROJECT_DAMAGED): if the file is missing required sections or
                                      contains invalid data.
        DomainError(PROJECT_PATH_TRAVERSAL): if the path contains traversal patterns.
    """
    _validate_path(file_path)

    if not os.path.isfile(file_path):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f".net file not found: {file_path!r}",
            details={"path": file_path},
        )

    parser = configparser.ConfigParser()
    try:
        with open(file_path, encoding="utf-8") as f:
            parser.read_file(f)
    except configparser.Error as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Failed to parse .net file: {e}",
            details={"path": file_path},
        ) from e
    except OSError as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Cannot read .net file: {e}",
            details={"path": file_path},
        ) from e

    if not parser.has_section("topology"):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=".net file missing [topology] section",
            details={"path": file_path},
        )

    devices = _parse_devices(parser, file_path)
    links = _parse_links(parser, file_path)

    return devices, links


def _parse_devices(parser: configparser.ConfigParser, file_path: str) -> list[NetDeviceEntry]:
    """Parse device sections from the .net file.

    Device sections are named [device-N] where N is a number.
    """
    devices: list[NetDeviceEntry] = []
    section_prefix = "device-"

    for section_name in parser.sections():
        if not section_name.startswith(section_prefix):
            continue

        try:
            section = parser[section_name]

            name = section.get("name", "").strip()
            if not name:
                raise ValueError("device name is empty")

            device_id_str = section.get("device_id", "").strip()
            if not device_id_str:
                raise ValueError("device_id is empty")
            device_id = int(device_id_str)

            device_type = section.get("type", "").strip() or None
            model = section.get("model", "").strip() or None

            x_str = section.get("x", "").strip()
            y_str = section.get("y", "").strip()
            x = int(x_str) if x_str else None
            y = int(y_str) if y_str else None

            devices.append(
                NetDeviceEntry(
                    name=name,
                    device_id=device_id,
                    device_type=device_type,
                    model=model,
                    x=x,
                    y=y,
                )
            )
        except (ValueError, KeyError) as e:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message=f"Invalid device section [{section_name}]: {e}",
                details={"path": file_path, "section": section_name},
            ) from e

    if not devices:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="No device sections found in .net file",
            details={"path": file_path},
        )

    return devices


def _parse_links(parser: configparser.ConfigParser, file_path: str) -> list[NetLinkEntry]:
    """Parse link sections from the .net file.

    Link sections are named [link-N] where N is a number.
    """
    links: list[NetLinkEntry] = []
    section_prefix = "link-"

    for section_name in parser.sections():
        if not section_name.startswith(section_prefix):
            continue

        try:
            section = parser[section_name]

            local_device = int(section.get("local_device", "").strip())
            local_if = section.get("local_if", "").strip()
            if not local_if:
                raise ValueError("local_if is empty")

            local_port_str = section.get("local_port", "").strip()
            local_port = int(local_port_str) if local_port_str else None

            remote_device = int(section.get("remote_device", "").strip())
            remote_if = section.get("remote_if", "").strip()
            if not remote_if:
                raise ValueError("remote_if is empty")

            remote_port_str = section.get("remote_port", "").strip()
            remote_port = int(remote_port_str) if remote_port_str else None

            links.append(
                NetLinkEntry(
                    local_device=local_device,
                    local_if=local_if,
                    local_port=local_port,
                    remote_device=remote_device,
                    remote_if=remote_if,
                    remote_port=remote_port,
                )
            )
        except (ValueError, KeyError) as e:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message=f"Invalid link section [{section_name}]: {e}",
                details={"path": file_path, "section": section_name},
            ) from e

    return links


def parse_net_topology(file_path: str) -> dict[str, Any]:
    """Parse a .net file and return a structured dict of topology data.

    Convenience function that returns all topology data in one dict.

    Args:
        file_path: Absolute path to the .net file.

    Returns:
        Dict with keys: "device_count", "link_count", "devices", "links".

    Raises:
        DomainError(PROJECT_DAMAGED): parse error.
        DomainError(PROJECT_PATH_TRAVERSAL): path traversal.
    """
    _validate_path(file_path)

    if not os.path.isfile(file_path):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f".net file not found: {file_path!r}",
            details={"path": file_path},
        )

    parser = configparser.ConfigParser()
    try:
        with open(file_path, encoding="utf-8") as f:
            parser.read_file(f)
    except configparser.Error as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Failed to parse .net file: {e}",
            details={"path": file_path},
        ) from e
    except OSError as e:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Cannot read .net file: {e}",
            details={"path": file_path},
        ) from e

    if not parser.has_section("topology"):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=".net file missing [topology] section",
            details={"path": file_path},
        )

    topology_section = parser["topology"]

    devices = _parse_devices(parser, file_path)
    links = _parse_links(parser, file_path)

    return {
        "device_count": topology_section.get("device_count", ""),
        "link_count": topology_section.get("link_count", ""),
        "devices": [
            {"name": d.name, "device_id": d.device_id, "type": d.device_type, "model": d.model}
            for d in devices
        ],
        "links": [
            {
                "local_device": link.local_device,
                "local_if": link.local_if,
                "remote_device": link.remote_device,
                "remote_if": link.remote_if,
            }
            for link in links
        ],
    }
