"""Tests for PolicyEngine implementation."""

from __future__ import annotations

import pytest

from h3c_hcl_mcp.domain.command import (
    CommandRequest,
    CommandTarget,
    CommandType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.infrastructure.policy.engine import PolicyEngineImpl
from h3c_hcl_mcp.infrastructure.policy.roles import Role
from h3c_hcl_mcp.infrastructure.settings import PolicySettings


@pytest.fixture
def read_only_settings() -> PolicySettings:
    return PolicySettings(mode="read_only")


@pytest.fixture
def write_enabled_settings() -> PolicySettings:
    return PolicySettings(mode="controlled_write")


@pytest.fixture
def lab_admin_settings() -> PolicySettings:
    return PolicySettings(mode="lab_admin")


@pytest.fixture
def engine_read_only(read_only_settings: PolicySettings) -> PolicyEngineImpl:
    engine = PolicyEngineImpl(read_only_settings)
    engine.set_role("admin_user", Role.ADMIN)
    engine.set_role("viewer_user", Role.VIEWER)
    engine.set_role("operator_user", Role.OPERATOR)
    return engine


class TestPolicyMode:
    """Default mode is read_only."""

    def test_default_mode_is_read_only(self, engine_read_only: PolicyEngineImpl) -> None:
        assert engine_read_only.mode == "read_only"
        assert not engine_read_only.is_write_enabled()

    def test_controlled_write_enabled(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        assert engine.is_write_enabled()

    def test_lab_admin_write_enabled(self, lab_admin_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(lab_admin_settings)
        assert engine.is_write_enabled()


class TestAuthorize:
    """Tool authorization checks roles."""

    @pytest.mark.asyncio
    async def test_viewer_can_list_projects(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("list_projects", "viewer_user")
        assert authorized

    @pytest.mark.asyncio
    async def test_viewer_cannot_execute_diagnostic(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("execute_diagnostic", "viewer_user")
        assert not authorized

    @pytest.mark.asyncio
    async def test_operator_can_execute_diagnostic(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("execute_diagnostic", "operator_user")
        assert authorized

    @pytest.mark.asyncio
    async def test_admin_can_plan_change(self, engine_read_only: PolicyEngineImpl) -> None:
        """Admin can plan change but is_write_enabled is false, so it's denied."""
        authorized = await engine_read_only.authorize("plan_change", "admin_user")
        assert not authorized  # write tools denied globally

    @pytest.mark.asyncio
    async def test_unknown_caller_is_viewer(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("list_projects", "unknown_person")
        assert authorized  # defaults to VIEWER

    @pytest.mark.asyncio
    async def test_unknown_caller_cannot_use_admin_tool(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("apply_change", "unknown_person")
        assert not authorized

    @pytest.mark.asyncio
    async def test_health_check_available_to_viewer(self, engine_read_only: PolicyEngineImpl) -> None:
        authorized = await engine_read_only.authorize("health_check", "viewer_user")
        assert authorized


class TestValidateCommand:
    """Command validation delegates to command_rules."""

    @pytest.mark.asyncio
    async def test_valid_display_command(self, engine_read_only: PolicyEngineImpl) -> None:
        request = CommandRequest(
            target=CommandTarget(project_id="test", device_id=1),
            command="display version",
            command_type=CommandType.DISPLAY,
        )
        result = await engine_read_only.validate_command(request)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejected_command_raises(self, engine_read_only: PolicyEngineImpl) -> None:
        request = CommandRequest(
            target=CommandTarget(project_id="test", device_id=1),
            command="reboot",
            command_type=CommandType.DISPLAY,
        )
        with pytest.raises(DomainError) as exc_info:
            await engine_read_only.validate_command(request)
        assert exc_info.value.code == ErrorCode.COMMAND_NOT_ALLOWED

    @pytest.mark.asyncio
    async def test_rejected_with_injection_raises(self, engine_read_only: PolicyEngineImpl) -> None:
        request = CommandRequest(
            target=CommandTarget(project_id="test", device_id=1),
            command="display version; reboot",
            command_type=CommandType.DISPLAY,
        )
        with pytest.raises(DomainError) as exc_info:
            await engine_read_only.validate_command(request)
        assert exc_info.value.code == ErrorCode.COMMAND_NOT_ALLOWED

    @pytest.mark.asyncio
    async def test_rejection_includes_details(self, engine_read_only: PolicyEngineImpl) -> None:
        request = CommandRequest(
            target=CommandTarget(project_id="test", device_id=1),
            command="reset saved",
            command_type=CommandType.DISPLAY,
        )
        with pytest.raises(DomainError) as exc_info:
            await engine_read_only.validate_command(request)
        assert exc_info.value.details
        assert exc_info.value.details["command"] == "reset saved"


class TestValidateChange:
    """validate_change returns risk levels."""

    @pytest.mark.asyncio
    async def test_read_only_raises_write_disabled(self, engine_read_only: PolicyEngineImpl) -> None:
        with pytest.raises(DomainError) as exc_info:
            await engine_read_only.validate_change("test_proj", 1, ["description test"])
        assert exc_info.value.code == ErrorCode.WRITE_DISABLED

    @pytest.mark.asyncio
    async def test_low_risk_change(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        risk = await engine.validate_change("test_proj", 1, ["description test interface"])
        assert risk == "R1"

    @pytest.mark.asyncio
    async def test_medium_risk_change(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        risk = await engine.validate_change(
            "test_proj", 1, ["interface GigabitEthernet 1/0/1", "port link-type trunk"]
        )
        assert risk == "R2"

    @pytest.mark.asyncio
    async def test_high_risk_reboot(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        risk = await engine.validate_change("test_proj", 1, ["reboot"])
        assert risk == "R3"

    @pytest.mark.asyncio
    async def test_high_risk_delete(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        risk = await engine.validate_change("test_proj", 1, ["delete flash:/test.cfg"])
        assert risk == "R3"

    @pytest.mark.asyncio
    async def test_zero_risk_display(self, write_enabled_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(write_enabled_settings)
        risk = await engine.validate_change("test_proj", 1, ["display version"])
        assert risk == "R0"


class TestRoleMapping:
    """Role assignment and lookup."""

    def test_default_role_is_viewer(self, read_only_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(read_only_settings)
        assert engine.get_role("anyone") == Role.VIEWER

    def test_set_and_get_role(self, read_only_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(read_only_settings)
        engine.set_role("alice", Role.ADMIN)
        assert engine.get_role("alice") == Role.ADMIN

    def test_custom_role_mapping(self, read_only_settings: PolicySettings) -> None:
        engine = PolicyEngineImpl(
            read_only_settings,
            role_mapping={"bob": Role.OPERATOR, "charlie": Role.ADMIN},
        )
        assert engine.get_role("bob") == Role.OPERATOR
        assert engine.get_role("charlie") == Role.ADMIN
        assert engine.get_role("unknown") == Role.VIEWER
