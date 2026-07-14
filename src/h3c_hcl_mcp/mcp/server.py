"""Composition Root — creates the MCP server with all tools and dependencies.

This module is responsible for:
1. Creating real adapter implementations (HCL, Security) wired from T3/T5
2. Keeping placeholders only for T4 (Comware transport) which is still in progress
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
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.audit.store import SQLiteAuditStore
from h3c_hcl_mcp.infrastructure.policy.approvals import ApprovalProviderImpl
from h3c_hcl_mcp.infrastructure.policy.engine import PolicyEngineImpl
from h3c_hcl_mcp.infrastructure.secrets import SecretProviderImpl
from h3c_hcl_mcp.infrastructure.settings import PolicySettings
from h3c_hcl_mcp.mcp.tools import (
    audit,
    h3c_change,
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

logger = logging.getLogger(__name__)

VERSION = "0.1.0-beta.1"
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
# Server factory
# ---------------------------------------------------------------------------


def create_server(
    hcl_projects_dirs: list[str] | None = None,
) -> FastMCP:
    """Create and configure the h3c-hcl-mcp FastMCP server.

    Wires real adapter implementations from:
    - T3: HCLProjectRepository, HCLRuntimeDiscovery
    - T4: FactsParser, InterfaceBriefParser, SessionManagerTransport
    - T5: PolicyEngineImpl, SQLiteAuditStore, SecretProviderImpl, ApprovalProviderImpl

    Placeholder remains for:
    - JobStore (in-memory placeholder is sufficient for v0.1)

    Args:
        hcl_projects_dirs: Directories to scan for HCL projects.
                           Defaults to H3C_CLOUD_LAB_PROJECTS env var or empty list.

    Returns:
        A fully configured FastMCP server ready to start via stdio.
    """
    import os

    if hcl_projects_dirs is None:
        env_dirs = os.environ.get("H3C_CLOUD_LAB_PROJECTS", "")
        hcl_projects_dirs = [d.strip() for d in env_dirs.split(";") if d.strip()]

    # --- Adapter instances ---

    # T3: HCL Adapter
    project_repo: ProjectRepository = HCLProjectRepository(
        projects_dirs=hcl_projects_dirs,
    )
    runtime_disc: RuntimeDiscovery = HCLRuntimeDiscovery()

    # T4: Comware parsers (composite — transport still placeholder)
    cmd_parser: CommandParser = _CompositeCommandParser()
    session_manager = DeviceSessionManager()
    device_transport: DeviceTransport = SessionManagerTransport(session_manager)

    # T5: Security
    policy_settings = PolicySettings()
    policy_engine: PolicyEngine = PolicyEngineImpl(settings=policy_settings)
    audit_sink: AuditSink = SQLiteAuditStore()
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
        name=SERVER_NAME,
        version=VERSION,
        instructions=(
            "HCL-Lab MCP Server provides discovery, monitoring, and CLI access "
            "for H3C Cloud Lab (HCL) network simulation environments. "
            "v0.1 supports read-only operations: project listing, topology, "
            "runtime state, and Comware CLI display/diagnostic commands."
        ),
    )

    # Register all tool modules with injected dependencies
    health.register(mcp, **adapters)
    hcl_projects.register(mcp, **adapters)
    hcl_runtime.register(mcp, **adapters)
    h3c_read.register(mcp, **adapters)
    h3c_change.register(mcp, **adapters)
    jobs.register(mcp, **adapters)
    audit.register(mcp, **adapters)

    real_count = sum(1 for v in adapters.values() if not isinstance(v, _PlaceholderJobStore))
    logger.info(
        "MCP server '%s' v%s created: %d real adapters, %d placeholders.",
        SERVER_NAME,
        VERSION,
        real_count,
        len(adapters) - real_count,
    )
    return mcp


async def main() -> None:
    """Entry point: create and run the MCP server via stdio."""
    print(f"{SERVER_NAME} v{VERSION} — starting stdio server...", file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    server = create_server()
    await server.run_stdio_async()
