"""Composition Root — creates the MCP server with all tools and dependencies.

This module is responsible for:
1. Creating real adapter implementations (HCL, Security) wired from T3/T5
2. Wiring the v0.1 Comware loopback-console transport and parsers
3. Assembling the FastMCP server instance
4. Registering all tool modules with injected dependencies
5. Starting the stdio transport loop
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from h3c_hcl_mcp.adapters.comware.parsers.facts import FactsParser
from h3c_hcl_mcp.adapters.comware.parsers.interfaces import InterfaceBriefParser
from h3c_hcl_mcp.adapters.comware.session_manager import (
    DeviceSessionManager,
    SessionManagerTransport,
)
from h3c_hcl_mcp.adapters.hcl.project_repository import HCLProjectRepository
from h3c_hcl_mcp.adapters.hcl.runtime_discovery import HCLRuntimeDiscovery
from h3c_hcl_mcp.application.runtime_service import ProjectAwareRuntimeDiscovery
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.audit.store import NullAuditStore, SQLiteAuditStore
from h3c_hcl_mcp.infrastructure.policy.approvals import ApprovalProviderImpl
from h3c_hcl_mcp.infrastructure.policy.engine import PolicyEngineImpl
from h3c_hcl_mcp.infrastructure.secrets import SecretProviderImpl
from h3c_hcl_mcp.infrastructure.settings import HCLSettings
from h3c_hcl_mcp.mcp.tools import (
    audit,
    h3c_read,
    hcl_projects,
    hcl_runtime,
    health,
    jobs,
)
from h3c_hcl_mcp.ports.approval_provider import ApprovalProvider
from h3c_hcl_mcp.ports.audit_sink import AuditSink
from h3c_hcl_mcp.ports.command_parser import CommandParser
from h3c_hcl_mcp.ports.device_transport import DeviceTransport
from h3c_hcl_mcp.ports.job_store import JobStatus, JobStore
from h3c_hcl_mcp.ports.policy_engine import PolicyEngine
from h3c_hcl_mcp.ports.project_repository import ProjectRepository
from h3c_hcl_mcp.ports.runtime_discovery import RuntimeDiscovery
from h3c_hcl_mcp.ports.secret_provider import SecretProvider
from h3c_hcl_mcp.version import VERSION

logger = logging.getLogger(__name__)

SERVER_NAME = "h3c-hcl-mcp"


# ---------------------------------------------------------------------------
# Composite CommandParser — delegates to real T4 sub-parsers
# ---------------------------------------------------------------------------


class _CompositeCommandParser(CommandParser):
    """Delegates to registered sub-parsers (FactsParser, InterfaceBriefParser, etc.).

    Falls back to returning raw output if no sub-parser claims the command.
    """

    def __init__(self) -> None:
        self._parsers: list[CommandParser] = [
            FactsParser(),
            InterfaceBriefParser(),
        ]

    def supports(self, model: str, version: str, command: str) -> bool:
        return any(p.supports(model, version, command) for p in self._parsers)

    def parse(self, raw_output: str, model: str, version: str, command: str) -> dict[str, Any]:
        for p in self._parsers:
            if p.supports(model, version, command):
                try:
                    return p.parse(raw_output, model, version, command)
                except Exception:
                    # Sub-parser failed — fall through to raw
                    pass
        return {"_raw": raw_output}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Placeholder implementations (only for JobStore — sufficient for v0.1)
# ---------------------------------------------------------------------------


class _PlaceholderJobStore(JobStore):
    """In-memory job store — works standalone until persistent store is needed."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    async def create(self, job_type: str, target: dict[str, Any] | None = None) -> str:
        import uuid

        job_id = str(uuid.uuid4())
        now = datetime.now().astimezone()
        self._jobs[job_id] = {
            "job_id": job_id,
            "type": job_type,
            "status": JobStatus.PENDING.value,
            "target": target,
            "result": None,
            "error": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        return job_id

    async def update(
        self,
        job_id: str,
        status: JobStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if job_id not in self._jobs:
            raise DomainError(
                code=ErrorCode.INVALID_ARGUMENT,
                message=f"Job {job_id} not found.",
            )
        self._jobs[job_id]["status"] = status.value
        self._jobs[job_id]["updated_at"] = datetime.now().astimezone().isoformat()
        if result is not None:
            self._jobs[job_id]["result"] = result
        if error is not None:
            self._jobs[job_id]["error"] = error

    async def get(self, job_id: str) -> dict[str, Any]:
        if job_id not in self._jobs:
            raise DomainError(
                code=ErrorCode.INVALID_ARGUMENT,
                message=f"Job {job_id} not found.",
            )
        return dict(self._jobs[job_id])

    async def cancel(self, job_id: str) -> bool:
        job = await self.get(job_id)
        if job["status"] in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
            await self.update(job_id, JobStatus.CANCELLED)
            return True
        return False


# ---------------------------------------------------------------------------
# Audit middleware wiring
# ---------------------------------------------------------------------------


def _wrap_tools_with_audit(mcp: FastMCP, audit_sink: AuditSink) -> None:
    """Wrap all registered tool functions with audit recording.

    After this call, every tool invocation will be recorded to the audit sink.
    """
    from h3c_hcl_mcp.mcp.audit_middleware import with_audit

    wrapped = 0
    for tool_name, tool in mcp._tool_manager._tools.items():
        if hasattr(tool, "fn"):
            tool.fn = with_audit(tool_name, audit_sink)(tool.fn)
            wrapped += 1
    logger.info("Audit middleware wrapped %d tools.", wrapped)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(
    settings: HCLSettings | None = None,
    hcl_projects_dirs: list[str] | None = None,
    config_path: str | None = None,
) -> FastMCP:
    """Create and configure the h3c-hcl-mcp FastMCP server.

    Wires real adapter implementations from:
    - T3: HCLProjectRepository, HCLRuntimeDiscovery
    - T4: FactsParser, InterfaceBriefParser, SessionManagerTransport
    - T5: PolicyEngineImpl, SQLiteAuditStore, SecretProviderImpl, ApprovalProviderImpl

    Placeholder remains for:
    - JobStore (in-memory placeholder is sufficient for v0.1)

    Args:
        settings: Pre-loaded HCLSettings instance (preferred for v0.1+).
        hcl_projects_dirs: Legacy — directories to scan for HCL projects.
        config_path: Legacy — optional path to YAML/JSON config file.

    Returns:
        A fully configured FastMCP server ready to start via stdio.
    """
    import os

    # --- Resolve settings ---
    if settings is None:
        # Legacy path: load from config file or env
        if config_path:
            from h3c_hcl_mcp.infrastructure.settings import load_settings

            settings = load_settings(config_path=config_path)
        else:
            # Fallback to defaults with env override
            from h3c_hcl_mcp.infrastructure.settings import HCLSettings as HCLS

            settings = HCLS()

    # --- Resolve projects_dirs (legacy CLI override) ---
    if hcl_projects_dirs is None:
        hcl_projects_dirs = list(settings.hcl.projects_dirs)
        if not hcl_projects_dirs:
            env_dirs = os.environ.get("H3C_CLOUD_LAB_PROJECTS", "")
            default_dir = os.path.join(os.environ.get("USERPROFILE", ""), "HCL", "Projects")
            if env_dirs:
                hcl_projects_dirs = [d.strip() for d in env_dirs.split(";") if d.strip()]
            elif os.path.isdir(default_dir):
                hcl_projects_dirs = [default_dir]
            else:
                hcl_projects_dirs = []

    # --- Adapter instances ---

    # T3: HCL Adapter
    project_repo: ProjectRepository = HCLProjectRepository(
        projects_dirs=hcl_projects_dirs,
    )
    runtime_adapter = HCLRuntimeDiscovery(
        fallback_telnet_base=settings.hcl.runtime_discovery.fallback_telnet_base,
        console_host=settings.hcl.runtime_discovery.console_host,
        install_dir=settings.hcl.install_dir,
        process_inspection=settings.hcl.runtime_discovery.process_inspection,
        log_observation=settings.hcl.runtime_discovery.log_observation,
        loopback_probe=settings.hcl.runtime_discovery.loopback_probe,
        max_probe_ports=settings.hcl.runtime_discovery.max_probe_ports,
    )
    runtime_disc: RuntimeDiscovery = ProjectAwareRuntimeDiscovery(
        project_repository=project_repo,
        delegate=runtime_adapter,
        topology_registrar=runtime_adapter,
    )

    # T4: Comware loopback-console transport and parsers
    cmd_parser: CommandParser = _CompositeCommandParser()
    session_manager = DeviceSessionManager(
        connect_timeout_seconds=settings.devices.connect_timeout_seconds,
    )
    device_transport: DeviceTransport = SessionManagerTransport(session_manager)

    # T5: Security
    policy_engine: PolicyEngine = PolicyEngineImpl(settings=settings.policy)
    if settings.audit.enabled:
        audit_db = settings.audit.database if settings.audit.database else None
        audit_sink: AuditSink = SQLiteAuditStore(db_path=audit_db)
    else:
        audit_sink = NullAuditStore()
    secret_provider: SecretProvider = SecretProviderImpl()
    approval_prov: ApprovalProvider = ApprovalProviderImpl()

    # Placeholder (standalone is fine for v0.1)
    job_store: JobStore = _PlaceholderJobStore()

    adapters: dict[str, Any] = {
        "project_repository": project_repo,
        "runtime_discovery": runtime_disc,
        "device_transport": device_transport,
        "command_parser": cmd_parser,
        "policy_engine": policy_engine,
        "approval_provider": approval_prov,
        "audit_sink": audit_sink,
        "job_store": job_store,
        "secret_provider": secret_provider,
    }

    # --- Create the MCP server ---
    mcp = FastMCP(
        name=settings.server.name,
        instructions=(
            "HCL-Lab MCP Server provides discovery, monitoring, and CLI access "
            "for H3C Cloud Lab (HCL) network simulation environments. "
            "v0.1 supports read-only operations: project listing, topology, "
            "runtime state, and Comware CLI display/diagnostic commands."
        ),
    )

    # Set serverInfo.version for MCP initialize response
    mcp._mcp_server.version = VERSION

    # Register all tool modules with injected dependencies
    health.register(mcp, **adapters, server_name=settings.server.name)
    hcl_projects.register(mcp, **adapters)
    hcl_runtime.register(mcp, **adapters)
    h3c_read.register(
        mcp,
        **adapters,
        server_settings=settings.server,
        device_settings=settings.devices,
    )
    # h3c_change.register(mcp, **adapters)  # v0.2 tools — disabled in v0.1
    jobs.register(mcp, **adapters)
    audit.register(mcp, **adapters)

    # --- Wrap call_tool with validation error reformatting (BUG-014) ---
    from h3c_hcl_mcp.mcp.validation_middleware import wrap_call_tool_with_validation

    wrap_call_tool_with_validation(
        mcp,
        audit_sink=audit_sink,
        timeout_seconds=settings.server.max_tool_seconds,
    )

    # --- Wrap all tools with audit middleware (BUG-009) ---
    _wrap_tools_with_audit(mcp, audit_sink)

    real_count = sum(1 for v in adapters.values() if not isinstance(v, _PlaceholderJobStore))
    logger.info(
        "MCP server '%s' v%s created: %d real adapters, %d placeholders.",
        settings.server.name,
        VERSION,
        real_count,
        len(adapters) - real_count,
    )
    return mcp


async def main(config_path: str | None = None) -> None:
    """Entry point: create and run the MCP server via stdio.

    Args:
        config_path: Optional path to YAML/JSON config file.
    """
    print(f"{SERVER_NAME} v{VERSION} -- starting stdio server...", file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    server = create_server(settings=None, config_path=config_path)
    await server.run_stdio_async()
