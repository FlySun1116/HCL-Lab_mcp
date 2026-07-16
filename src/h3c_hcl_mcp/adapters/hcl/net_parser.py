"""Parse HCL ``.net`` topology files.

HCL 5.10.x writes ConfigObj-style nested sections, not standard INI.  Older
synthetic fixtures used by the project use a small INI schema.  Both formats
are supported because existing users may already have exported synthetic
projects for tests and demonstrations.
"""

from __future__ import annotations

import configparser
import os
import re
from collections.abc import Iterable
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
    """Reject path traversal patterns."""
    if ".." in file_path:
        raise DomainError(
            code=ErrorCode.PROJECT_PATH_TRAVERSAL,
            message=f"Path traversal detected: {file_path!r}",
            details={"path": file_path},
        )


def _read_net_text(file_path: str) -> str:
    _validate_path(file_path)
    if not os.path.isfile(file_path):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f".net file not found: {file_path!r}",
            details={"path": file_path},
        )
    try:
        with open(file_path, encoding="utf-8-sig") as file:
            return file.read()
    except (OSError, UnicodeError) as exc:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Cannot read .net file: {exc}",
            details={"path": file_path},
        ) from exc


def parse_net_file(file_path: str) -> tuple[list[NetDeviceEntry], list[NetLinkEntry]]:
    """Parse a real HCL 5.10.x or legacy synthetic ``.net`` file."""
    text = _read_net_text(file_path)
    if any(line.strip().lower() == "[topology]" for line in text.splitlines()):
        return _parse_synthetic_net(text, file_path)
    return _parse_hcl_510x_net(text, file_path)


def _parse_synthetic_net(text: str, file_path: str) -> tuple[list[NetDeviceEntry], list[NetLinkEntry]]:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text, source=file_path)
    except configparser.Error as exc:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=f"Failed to parse .net file: {exc}",
            details={"path": file_path},
        ) from exc

    if not parser.has_section("topology"):
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message=".net file missing [topology] section",
            details={"path": file_path},
        )
    return _parse_devices(parser, file_path), _parse_links(parser, file_path)


_TOP_SECTION_RE = re.compile(r"^\[([^\[\]]+)]$")
_NESTED_SECTION_RE = re.compile(r"^\s*\[\[([^\[\]]+)]]\s*$")
_KEY_VALUE_RE = re.compile(r"^\s*([^=]+?)\s*=\s*(.*?)\s*$")


def _parse_hcl_510x_net(text: str, file_path: str) -> tuple[list[NetDeviceEntry], list[NetLinkEntry]]:
    """Parse the nested ConfigObj representation emitted by HCL 5.10.x."""
    blocks: list[tuple[str, dict[str, str]]] = []
    parent_section = ""
    block_name: str | None = None
    block_values: dict[str, str] = {}

    def flush_block() -> None:
        nonlocal block_name, block_values
        # Notes also use nested sections, but only device blocks contain an ID.
        if block_name is not None and "device_id" in block_values:
            blocks.append((block_name, block_values))
        block_name = None
        block_values = {}

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue

        nested_match = _NESTED_SECTION_RE.match(raw_line)
        if nested_match:
            flush_block()
            # Real devices live below [vbox HOST:PORT].  Keeping this boundary
            # avoids interpreting [[NOTE n]] sections as topology devices.
            if parent_section.casefold().startswith("vbox "):
                block_name = nested_match.group(1).strip()
            continue

        top_match = _TOP_SECTION_RE.match(stripped)
        if top_match:
            flush_block()
            parent_section = top_match.group(1).strip()
            continue

        if block_name is not None:
            key_value_match = _KEY_VALUE_RE.match(raw_line)
            if key_value_match:
                block_values[key_value_match.group(1).strip()] = key_value_match.group(2).strip().strip('"')

    flush_block()

    devices: list[NetDeviceEntry] = []
    values_by_id: dict[int, dict[str, str]] = {}
    seen_names: set[str] = set()
    for header, values in blocks:
        try:
            model, name = _split_device_header(header)
            device_id = int(values["device_id"])
            if device_id <= 0:
                raise ValueError("device_id must be positive")
            if device_id in values_by_id:
                raise ValueError(f"duplicate device_id {device_id}")
            if name in seen_names:
                raise ValueError(f"duplicate device name {name!r}")
            device = NetDeviceEntry(
                name=name,
                device_id=device_id,
                device_type=model,
                model=model,
                x=_parse_coordinate(values.get("x")),
                y=_parse_coordinate(values.get("y")),
            )
        except (KeyError, ValueError) as exc:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message=f"Invalid HCL device section [[{header}]]: {exc}",
                details={"path": file_path, "section": header},
            ) from exc
        devices.append(device)
        values_by_id[device_id] = values
        seen_names.add(name)

    if not devices:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="No HCL device sections found in .net file",
            details={"path": file_path},
        )

    links = _links_from_hcl_devices(devices, values_by_id)
    return devices, links


def _split_device_header(header: str) -> tuple[str, str]:
    parts = header.split(maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("expected '<model> <resourceName>'")
    return parts[0], parts[1]


def _parse_coordinate(value: str | None) -> int | None:
    if value is None or not value:
        return None
    return int(float(value))


def _links_from_hcl_devices(
    devices: Iterable[NetDeviceEntry], values_by_id: dict[int, dict[str, str]]
) -> list[NetLinkEntry]:
    device_list = list(devices)
    # Longest-first prevents a prefix name (for example SW_1) from stealing a
    # reference to another device (for example SW_10).
    devices_by_name = sorted(device_list, key=lambda device: len(device.name), reverse=True)
    links: list[NetLinkEntry] = []
    seen: set[tuple[tuple[int, str], tuple[int, str]]] = set()

    for local in device_list:
        for local_if, raw_target in values_by_id[local.device_id].items():
            remote = next(
                (candidate for candidate in devices_by_name if raw_target.startswith(f"{candidate.name} ")),
                None,
            )
            if remote is None:
                continue
            remote_if = raw_target[len(remote.name) :].strip()
            if not remote_if:
                continue

            endpoint_a = (local.device_id, local_if)
            endpoint_b = (remote.device_id, remote_if)
            identity = (endpoint_a, endpoint_b) if endpoint_a <= endpoint_b else (endpoint_b, endpoint_a)
            if identity in seen:
                continue
            seen.add(identity)
            links.append(
                NetLinkEntry(
                    local_device=local.device_id,
                    local_if=local_if,
                    local_port=None,
                    remote_device=remote.device_id,
                    remote_if=remote_if,
                    remote_port=None,
                )
            )
    return links


def _parse_devices(parser: configparser.ConfigParser, file_path: str) -> list[NetDeviceEntry]:
    devices: list[NetDeviceEntry] = []
    for section_name in parser.sections():
        if not section_name.startswith("device-"):
            continue
        try:
            section = parser[section_name]
            name = section.get("name", "").strip()
            if not name:
                raise ValueError("device name is empty")
            device_id_text = section.get("device_id", "").strip()
            if not device_id_text:
                raise ValueError("device_id is empty")
            x_text = section.get("x", "").strip()
            y_text = section.get("y", "").strip()
            devices.append(
                NetDeviceEntry(
                    name=name,
                    device_id=int(device_id_text),
                    device_type=section.get("type", "").strip() or None,
                    model=section.get("model", "").strip() or None,
                    x=int(float(x_text)) if x_text else None,
                    y=int(float(y_text)) if y_text else None,
                )
            )
        except (ValueError, KeyError) as exc:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message=f"Invalid device section [{section_name}]: {exc}",
                details={"path": file_path, "section": section_name},
            ) from exc
    if not devices:
        raise DomainError(
            code=ErrorCode.PROJECT_DAMAGED,
            message="No device sections found in .net file",
            details={"path": file_path},
        )
    return devices


def _parse_links(parser: configparser.ConfigParser, file_path: str) -> list[NetLinkEntry]:
    links: list[NetLinkEntry] = []
    for section_name in parser.sections():
        if not section_name.startswith("link-"):
            continue
        try:
            section = parser[section_name]
            local_if = section.get("local_if", "").strip()
            remote_if = section.get("remote_if", "").strip()
            if not local_if or not remote_if:
                raise ValueError("local_if and remote_if are required")
            local_port_text = section.get("local_port", "").strip()
            remote_port_text = section.get("remote_port", "").strip()
            links.append(
                NetLinkEntry(
                    local_device=int(section.get("local_device", "").strip()),
                    local_if=local_if,
                    local_port=int(local_port_text) if local_port_text else None,
                    remote_device=int(section.get("remote_device", "").strip()),
                    remote_if=remote_if,
                    remote_port=int(remote_port_text) if remote_port_text else None,
                )
            )
        except (ValueError, KeyError) as exc:
            raise DomainError(
                code=ErrorCode.PROJECT_DAMAGED,
                message=f"Invalid link section [{section_name}]: {exc}",
                details={"path": file_path, "section": section_name},
            ) from exc
    return links


def parse_net_topology(file_path: str) -> dict[str, Any]:
    """Return a serializable view of either supported topology format."""
    devices, links = parse_net_file(file_path)
    return {
        "device_count": str(len(devices)),
        "link_count": str(len(links)),
        "devices": [
            {
                "name": device.name,
                "device_id": device.device_id,
                "type": device.device_type,
                "model": device.model,
            }
            for device in devices
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
