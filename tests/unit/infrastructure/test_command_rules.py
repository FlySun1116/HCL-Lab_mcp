"""Tests for command validation rules and injection detection."""

from __future__ import annotations

import pytest

from h3c_hcl_mcp.domain.command import CommandType
from h3c_hcl_mcp.infrastructure.policy.command_rules import (
    ALLOWED_DIAGNOSTIC_COMMANDS,
    ALLOWED_DISPLAY_COMMANDS,
    validate_command,
)


class TestAllowedCommands:
    """All allowlisted commands should pass validation."""

    @pytest.mark.parametrize("command", ALLOWED_DISPLAY_COMMANDS)
    def test_display_commands_allowed(self, command: str) -> None:
        is_valid, reason = validate_command(command, CommandType.DISPLAY)
        assert is_valid, f"Expected '{command}' to be allowed, got: {reason}"

    @pytest.mark.parametrize(
        "command",
        [f"{command} 192.0.2.1" for command in ALLOWED_DIAGNOSTIC_COMMANDS],
    )
    def test_diagnostic_commands_allowed(self, command: str) -> None:
        is_valid, reason = validate_command(command, CommandType.DIAGNOSTIC)
        assert is_valid, f"Expected '{command}' to be allowed, got: {reason}"

    def test_display_with_extra_args_allowed(self) -> None:
        """display commands with additional arguments should be allowed."""
        is_valid, reason = validate_command(
            "display current-configuration interface GigabitEthernet 1/0/1",
            CommandType.DISPLAY,
        )
        assert is_valid, f"Expected allowed, got: {reason}"

    def test_display_interface_brief_with_args(self) -> None:
        is_valid, reason = validate_command(
            "display interface brief description",
            CommandType.DISPLAY,
        )
        assert is_valid, f"Expected allowed, got: {reason}"

    def test_ping_basic(self) -> None:
        is_valid, reason = validate_command("ping 192.168.1.1", CommandType.DIAGNOSTIC)
        assert is_valid, f"Expected allowed, got: {reason}"

    def test_tracert_basic(self) -> None:
        is_valid, reason = validate_command("tracert 192.168.1.1", CommandType.DIAGNOSTIC)
        assert is_valid, f"Expected allowed, got: {reason}"


class TestInjectionRejection:
    """All injection patterns must be rejected."""

    def test_newline_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version\nreboot",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "newline" in reason.lower()

    def test_carriage_return_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version\rreboot",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "newline" in reason.lower()

    def test_semicolon_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version; reboot",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "separator" in reason.lower()

    def test_pipe_rejected_in_display(self) -> None:
        """Pipe is rejected in fully controlled context (defense-in-depth)."""
        is_valid, reason = validate_command(
            "display current-configuration | include password",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason is not None

    def test_output_redirect_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version > flash:/version.txt",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "redirection" in reason.lower()

    def test_input_redirect_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version < flash:/input.txt",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "redirection" in reason.lower()

    def test_shell_escape_exclamation_rejected(self) -> None:
        is_valid, reason = validate_command(
            "!reboot",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "shell escape" in reason.lower()

    def test_shell_escape_dollar_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display $variable",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "shell escape" in reason.lower()

    def test_backtick_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display `reboot`",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "backtick" in reason.lower()

    def test_control_character_rejected(self) -> None:
        is_valid, reason = validate_command(
            "display version\x00hidden",
            CommandType.DISPLAY,
        )
        assert not is_valid
        assert reason and "control character" in reason.lower()

    def test_empty_command_rejected(self) -> None:
        is_valid, reason = validate_command("", CommandType.DISPLAY)
        assert not is_valid
        assert reason and "empty" in reason.lower()

    def test_whitespace_only_rejected(self) -> None:
        is_valid, reason = validate_command("   ", CommandType.DISPLAY)
        assert not is_valid
        assert reason and "empty" in reason.lower()


class TestDangerousPatterns:
    """All dangerous commands must be rejected regardless of command type."""

    @pytest.mark.parametrize(
        "dangerous",
        [
            "reboot",
            "reset saved-configuration",
            "format flash:",
            "delete flash:/test.cfg",
            "erase startup-configuration",
            "save force",
            "copy running-config startup-config",
            "tftp 192.168.1.1 put config.cfg",
            "ftp 192.168.1.1",
            "startup saved-configuration test.cfg",
            "undo info-center enable",
            "system-view",
        ],
    )
    def test_dangerous_rejected(self, dangerous: str) -> None:
        is_valid, reason = validate_command(dangerous, CommandType.DISPLAY)
        assert not is_valid, f"Expected '{dangerous}' to be rejected"
        assert reason is not None


class TestPingInjection:
    """Ping/tracert with injection payloads must be rejected."""

    def test_ping_with_semicolon_rejected(self) -> None:
        is_valid, reason = validate_command(
            "ping 127.0.0.1; reboot",
            CommandType.DIAGNOSTIC,
        )
        assert not is_valid

    def test_ping_with_pipe_rejected(self) -> None:
        is_valid, reason = validate_command(
            "ping 127.0.0.1 | reboot",
            CommandType.DIAGNOSTIC,
        )
        assert not is_valid
        assert reason is not None

    def test_ping_with_reboot_keyword_rejected(self) -> None:
        is_valid, reason = validate_command(
            "ping 127.0.0.1 reboot",
            CommandType.DIAGNOSTIC,
        )
        assert not is_valid
        # This will be caught by either diagnostic injection or denied substring

    def test_tracert_with_semicolon_rejected(self) -> None:
        is_valid, reason = validate_command(
            "tracert 127.0.0.1; reset config",
            CommandType.DIAGNOSTIC,
        )
        assert not is_valid

    def test_tracert_with_shell_escape_rejected(self) -> None:
        is_valid, reason = validate_command(
            "tracert 127.0.0.1 `id`",
            CommandType.DIAGNOSTIC,
        )
        assert not is_valid

    def test_ping_not_in_allowlist_as_display(self) -> None:
        """'ping' is not a display command — must use DIAGNOSTIC type."""
        is_valid, reason = validate_command("ping 127.0.0.1", CommandType.DISPLAY)
        assert not is_valid
        assert reason and ("allowlist" in reason.lower() or "not in" in reason.lower())

    @pytest.mark.parametrize(
        "command",
        [
            "ping -c 101 192.0.2.1",
            "ping -c 5 192.0.2.1 -c 100",
            "ping -s 65500 192.0.2.1",
            "ping -c 5 host name",
            "tracert -m 256 192.0.2.1",
            "tracert -m 30 192.0.2.1 -m 255",
            "tracert -a 192.0.2.2 192.0.2.1",
        ],
    )
    def test_unsupported_or_oversized_diagnostic_arguments_rejected(self, command: str) -> None:
        is_valid, reason = validate_command(command, CommandType.DIAGNOSTIC)
        assert not is_valid
        assert reason is not None

    @pytest.mark.parametrize(
        "command",
        [
            "ping 192.0.2.1",
            "ping -c 100 host.example",
            "ping -c 1 ::1",
            "tracert 192.0.2.1",
            "tracert -m 255 2001:db8::1",
        ],
    )
    def test_supported_diagnostic_arguments_allowed(self, command: str) -> None:
        is_valid, reason = validate_command(command, CommandType.DIAGNOSTIC)
        assert is_valid
        assert reason is None


class TestSQLInjectionDefense:
    """SQL injection patterns are rejected for defense-in-depth."""

    @pytest.mark.parametrize(
        "payload",
        [
            "select * from users",
            "insert into users values",
            "delete from config",
            "update users set",
            "drop table users",
            "union select * from",
            "1' or '1'='1",
        ],
    )
    def test_sql_patterns_rejected(self, payload: str) -> None:
        is_valid, reason = validate_command(payload, CommandType.DISPLAY)
        assert not is_valid, f"SQL pattern '{payload}' should be rejected"


class TestConfigCommandsBlocked:
    """Config/save/reset command types are always rejected in read_only mode."""

    def test_config_type_rejected(self) -> None:
        is_valid, reason = validate_command(
            "interface GigabitEthernet 1/0/1",
            CommandType.CONFIG,
        )
        assert not is_valid
        assert reason and "not allowed" in reason.lower()

    def test_save_type_rejected(self) -> None:
        is_valid, reason = validate_command("save force", CommandType.SAVE)
        assert not is_valid

    def test_reset_type_rejected(self) -> None:
        is_valid, reason = validate_command("reset counters", CommandType.RESET)
        assert not is_valid
