"""AuditSink implementation — SQLite-backed audit trail.

All tool invocations are recorded as append-only audit events.
Supports querying by request_id, tool, device, and time range.
Thread-safe via WAL journal mode.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.audit_sink import AuditSink

logger = logging.getLogger(__name__)


class SQLiteAuditStore(AuditSink):
    """SQLite-based persistent audit trail.

    Uses WAL journal mode for concurrent read/write access.
    All write operations are protected by a threading.Lock.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            import sys

            if sys.platform == "win32":
                base = Path(
                    __import__("os").environ.get(
                        "LOCALAPPDATA",
                        str(Path.home() / "AppData" / "Local"),
                    )
                )
            else:
                base = Path(
                    __import__("os").environ.get(
                        "XDG_DATA_HOME",
                        str(Path.home() / ".local" / "share"),
                    )
                )
            db_dir = base / "h3c-hcl-mcp"
        else:
            db_dir = Path(db_path).parent
            if db_dir.name.endswith(".db"):
                db_dir = Path(db_path)

        db_dir.mkdir(parents=True, exist_ok=True)
        db_file = db_dir if not str(db_path).endswith(".db") else Path(db_path)
        if not str(db_path).endswith(".db") if db_path else True:
            db_file = db_dir / "audit.db"
        else:
            db_file = Path(db_path)

        self._db_path = str(db_file)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("Audit store initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript(schema_sql)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new SQLite connection."""
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # AuditSink ABC implementation
    # ------------------------------------------------------------------

    async def append(self, event: AuditEvent) -> None:
        """Insert an audit event (thread-safe)."""
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._append_sync, event)

    def _append_sync(self, event: AuditEvent) -> None:
        """Synchronous insert under lock."""
        target_json = json.dumps(event.target, ensure_ascii=False) if event.target else None
        timestamp_iso = event.timestamp.isoformat()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """INSERT INTO audit_events
                           (event_id, request_id, caller, tool, target,
                            policy_result, change_summary, timestamp,
                            duration_ms, error_code)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            event.event_id,
                            event.request_id,
                            event.caller,
                            event.tool,
                            target_json,
                            event.policy_result,
                            event.change_summary,
                            timestamp_iso,
                            event.duration_ms,
                            event.error_code,
                        ),
                    )
            except sqlite3.Error as e:
                logger.error("Failed to append audit event: %s", e)
                raise DomainError(
                    ErrorCode.INTERNAL_ERROR,
                    f"audit append failed: {e}",
                ) from e

    async def query(
        self,
        request_id: str | None = None,
        tool: str | None = None,
        target_device: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters.

        Returns events in reverse chronological order.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._query_sync,
            request_id,
            tool,
            target_device,
            since,
            until,
            limit,
        )

    def _query_sync(
        self,
        request_id: str | None,
        tool: str | None,
        target_device: int | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> list[AuditEvent]:
        """Synchronous query."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if request_id:
            where_clauses.append("request_id = ?")
            params.append(request_id)
        if tool:
            where_clauses.append("tool = ?")
            params.append(tool)
        if target_device is not None:
            # target_device is embedded in the target JSON column
            where_clauses.append("CAST(json_extract(target, '$.device_id') AS INTEGER) = ?")
            params.append(target_device)
        if since:
            where_clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            where_clauses.append("timestamp <= ?")
            params.append(until.isoformat())

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query_sql = f"SELECT * FROM audit_events WHERE {where_sql} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        try:
            with self._get_connection() as conn:
                rows = conn.execute(query_sql, params).fetchall()
        except sqlite3.Error as e:
            logger.error("Audit query failed: %s", e)
            raise DomainError(
                ErrorCode.INTERNAL_ERROR,
                f"audit query failed: {e}",
            ) from e

        events: list[AuditEvent] = []
        for row in rows:
            target_dict: dict | None = None
            if row["target"]:
                try:
                    target_dict = json.loads(row["target"])
                except json.JSONDecodeError:
                    target_dict = {"raw": row["target"]}

            timestamp = datetime.fromisoformat(row["timestamp"])

            events.append(
                AuditEvent(
                    event_id=row["event_id"],
                    request_id=row["request_id"],
                    caller=row["caller"],
                    tool=row["tool"],
                    target=target_dict,
                    policy_result=row["policy_result"],
                    change_summary=row["change_summary"],
                    timestamp=timestamp,
                    duration_ms=row["duration_ms"],
                    error_code=row["error_code"],
                )
            )

        return events
