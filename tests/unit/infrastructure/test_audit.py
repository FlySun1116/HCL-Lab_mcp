"""Tests for SQLite audit store."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from h3c_hcl_mcp.domain.audit import AuditEvent
from h3c_hcl_mcp.infrastructure.audit.store import SQLiteAuditStore


@pytest.fixture
def audit_store() -> SQLiteAuditStore:
    """Create an audit store backed by a temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_audit_")
    os.close(fd)
    store = SQLiteAuditStore(db_path=path)
    yield store
    # Cleanup
    try:
        os.unlink(path)
        os.unlink(path + "-wal") if os.path.exists(path + "-wal") else None
        os.unlink(path + "-shm") if os.path.exists(path + "-shm") else None
    except OSError:
        pass


_DEFAULT_TARGET: dict = {"project_id": "test_proj", "device_id": 1}

_UNSET = object()


def _make_event(
    event_id: str = "evt-001",
    request_id: str = "req-001",
    caller: str = "test_user",
    tool: str = "execute_display",
    target: dict | None = _UNSET,  # type: ignore[assignment]
    policy_result: str = "allowed",
    change_summary: str | None = None,
    timestamp: datetime | None = None,
    duration_ms: float = 42.0,
    error_code: str | None = None,
) -> AuditEvent:
    if target is _UNSET:  # type: ignore[comparison-overlap]
        target = _DEFAULT_TARGET
    return AuditEvent(
        event_id=event_id,
        request_id=request_id,
        caller=caller,
        tool=tool,
        target=target,
        policy_result=policy_result,
        change_summary=change_summary,
        timestamp=timestamp or datetime.now(UTC),
        duration_ms=duration_ms,
        error_code=error_code,
    )


class TestAppendAndQuery:
    """Events can be appended and then queried back."""

    @pytest.mark.asyncio
    async def test_append_single_event(self, audit_store: SQLiteAuditStore) -> None:
        event = _make_event()
        await audit_store.append(event)

        results = await audit_store.query(limit=10)
        assert len(results) == 1
        assert results[0].event_id == "evt-001"
        assert results[0].tool == "execute_display"

    @pytest.mark.asyncio
    async def test_append_multiple_events(self, audit_store: SQLiteAuditStore) -> None:
        for i in range(5):
            await audit_store.append(_make_event(event_id=f"evt-{i:03d}", request_id=f"req-{i:03d}"))

        results = await audit_store.query(limit=100)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_query_by_request_id(self, audit_store: SQLiteAuditStore) -> None:
        await audit_store.append(_make_event(event_id="evt-a", request_id="req-find-me"))
        await audit_store.append(_make_event(event_id="evt-b", request_id="req-other"))

        results = await audit_store.query(request_id="req-find-me", limit=10)
        assert len(results) == 1
        assert results[0].event_id == "evt-a"

    @pytest.mark.asyncio
    async def test_query_by_tool(self, audit_store: SQLiteAuditStore) -> None:
        await audit_store.append(_make_event(event_id="evt-a", tool="get_device_facts"))
        await audit_store.append(_make_event(event_id="evt-b", tool="execute_display"))
        await audit_store.append(_make_event(event_id="evt-c", tool="execute_display"))

        results = await audit_store.query(tool="execute_display", limit=10)
        assert len(results) == 2
        tool_names = {r.tool for r in results}
        assert tool_names == {"execute_display"}

    @pytest.mark.asyncio
    async def test_query_by_device_id(self, audit_store: SQLiteAuditStore) -> None:
        await audit_store.append(_make_event(event_id="evt-a", target={"project_id": "proj", "device_id": 1}))
        await audit_store.append(_make_event(event_id="evt-b", target={"project_id": "proj", "device_id": 2}))

        results = await audit_store.query(target_device=1, limit=10)
        assert len(results) == 1
        assert results[0].event_id == "evt-a"

    @pytest.mark.asyncio
    async def test_query_by_time_range(self, audit_store: SQLiteAuditStore) -> None:
        now = datetime.now(UTC)
        past = now - timedelta(hours=2)
        future = now + timedelta(hours=2)
        very_past = now - timedelta(hours=4)

        await audit_store.append(_make_event(event_id="evt-a", timestamp=now))
        await audit_store.append(_make_event(event_id="evt-b", timestamp=very_past))

        results = await audit_store.query(since=past, until=future, limit=10)
        assert len(results) == 1
        assert results[0].event_id == "evt-a"

    @pytest.mark.asyncio
    async def test_query_with_limit(self, audit_store: SQLiteAuditStore) -> None:
        for i in range(10):
            await audit_store.append(_make_event(event_id=f"evt-{i:03d}"))

        results = await audit_store.query(limit=3)
        assert len(results) == 3


class TestEventPreservation:
    """All event fields should be preserved round-trip."""

    @pytest.mark.asyncio
    async def test_all_fields_preserved(self, audit_store: SQLiteAuditStore) -> None:
        timestamp = datetime.now(UTC)
        event = _make_event(
            event_id="evt-full",
            request_id="req-full",
            caller="alice",
            tool="get_config",
            target={"project_id": "lab1", "device_id": 5, "device_name": "Core-Switch"},
            policy_result="denied",
            change_summary="Attempted config read — denied by policy",
            timestamp=timestamp,
            duration_ms=1234.5,
            error_code="POLICY_DENIED",
        )
        await audit_store.append(event)

        results = await audit_store.query(limit=1)
        assert len(results) == 1
        r = results[0]
        assert r.event_id == "evt-full"
        assert r.request_id == "req-full"
        assert r.caller == "alice"
        assert r.tool == "get_config"
        assert r.target == {"project_id": "lab1", "device_id": 5, "device_name": "Core-Switch"}
        assert r.policy_result == "denied"
        assert r.change_summary == "Attempted config read — denied by policy"
        assert r.duration_ms == 1234.5
        assert r.error_code == "POLICY_DENIED"

    @pytest.mark.asyncio
    async def test_null_target(self, audit_store: SQLiteAuditStore) -> None:
        event = _make_event(event_id="evt-null-target", target=None)
        await audit_store.append(event)

        results = await audit_store.query(limit=1)
        assert results[0].target is None

    @pytest.mark.asyncio
    async def test_null_change_summary(self, audit_store: SQLiteAuditStore) -> None:
        event = _make_event(event_id="evt-no-summary", change_summary=None)
        await audit_store.append(event)

        results = await audit_store.query(limit=1)
        assert results[0].change_summary is None
