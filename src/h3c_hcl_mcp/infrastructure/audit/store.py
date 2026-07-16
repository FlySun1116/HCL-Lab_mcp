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
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.audit_sink import AuditSink

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Normalize aware or legacy naive timestamps for SQLite ordering."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class NullAuditStore(AuditSink):
    """No-op audit sink used only when auditing is explicitly disabled."""

    async def append(self, event: AuditEvent) -> None:
        del event

    async def query(
        self,
        request_id: str | None = None,
        tool: str | None = None,
        target_device: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        del request_id, tool, target_device, since, until, limit
        return []


class SQLiteAuditStore(AuditSink):
    """SQLite-based persistent audit trail.

    Uses WAL journal mode for concurrent read/write access.
    All write operations are protected by a threading.Lock.
    """

    def __init__(self, db_path: str | None = None) -> None:
        import sys

        if db_path is None:
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
            db_file = db_dir / "audit.db"
        elif db_path.endswith(".db"):
            db_dir = Path(db_path).parent
            db_file = Path(db_path)
        else:
            db_dir = Path(db_path)
            db_file = db_dir / "audit.db"

        db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_file)
        self._lock = threading.Lock()
        self._init_db()
        logger.info("Audit store initialized at %s", self._db_path)

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")

        # sqlite3.Connection's context manager commits or rolls back but does
        # not close the connection. This store opens one connection per
        # operation, so every call must close it explicitly.
        with closing(self._get_connection()) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript(schema_sql)
            # Databases created before the outcome field existed must remain
            # readable. CREATE TABLE IF NOT EXISTS cannot add new columns.
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(audit_events)")}
            if "outcome" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN outcome TEXT NOT NULL DEFAULT 'success'")
                conn.execute(
                    "UPDATE audit_events SET outcome = 'error' "
                    "WHERE error_code IS NOT NULL AND error_code != ''"
                )

            # SQLite compares ISO timestamps as TEXT. Normalize legacy rows
            # to UTC so offsets such as +08:00 cannot break filtering/order.
            for row in conn.execute("SELECT event_id, timestamp FROM audit_events"):
                try:
                    normalized = _as_utc(datetime.fromisoformat(str(row[1]))).isoformat()
                except (TypeError, ValueError):
                    continue
                if normalized != row[1]:
                    conn.execute(
                        "UPDATE audit_events SET timestamp = ? WHERE event_id = ?",
                        (normalized, row[0]),
                    )
            conn.commit()

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
        timestamp_iso = _as_utc(event.timestamp).isoformat()

        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    conn.execute(
                        """INSERT INTO audit_events
                           (event_id, request_id, caller, tool, target,
                            policy_result, outcome, change_summary, timestamp,
                            duration_ms, error_code)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            event.event_id,
                            event.request_id,
                            event.caller,
                            event.tool,
                            target_json,
                            event.policy_result,
                            event.outcome,
                            event.change_summary,
                            timestamp_iso,
                            event.duration_ms,
                            event.error_code,
                        ),
                    )
                    conn.commit()
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
            params.append(_as_utc(since).isoformat())
        if until:
            where_clauses.append("timestamp <= ?")
            params.append(_as_utc(until).isoformat())

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query_sql = f"SELECT * FROM audit_events WHERE {where_sql} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        try:
            with closing(self._get_connection()) as conn:
                rows = conn.execute(query_sql, params).fetchall()
        except sqlite3.Error as e:
            logger.error("Audit query failed: %s", e)
            raise DomainError(
                ErrorCode.INTERNAL_ERROR,
                f"audit query failed: {e}",
            ) from e

        events: list[AuditEvent] = []
        for row in rows:
            target_dict: dict[str, object] | None = None
            if row["target"]:
                try:
                    target_dict = json.loads(row["target"])
                except json.JSONDecodeError:
                    target_dict = {"raw": row["target"]}

            timestamp = _as_utc(datetime.fromisoformat(row["timestamp"]))

            events.append(
                AuditEvent(
                    event_id=row["event_id"],
                    request_id=row["request_id"],
                    caller=row["caller"],
                    tool=row["tool"],
                    target=target_dict,
                    policy_result=row["policy_result"],
                    outcome=row["outcome"],
                    change_summary=row["change_summary"],
                    timestamp=timestamp,
                    duration_ms=row["duration_ms"],
                    error_code=row["error_code"],
                )
            )

        return events
