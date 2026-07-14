"""Unit tests for Comware CLI prompt state machine (prompt.py)."""

from h3c_hcl_mcp.adapters.comware.prompt import (
    detect_prompt,
    extract_sysname,
    is_login_prompt,
    is_more_prompt,
    is_system_view,
    is_user_view,
    normalize_prompt,
)


class TestDetectPrompt:
    """Prompt detection across all Comware CLI modes."""

    def test_user_view_default(self):
        buf = "\r\n<H3C>"
        assert detect_prompt(buf) == "<H3C>"

    def test_user_view_renamed(self):
        buf = "\r\n<CoreSwitch>"
        assert detect_prompt(buf) == "<CoreSwitch>"

    def test_user_view_with_trailing_space(self):
        buf = "some output\r\n<H3C> "
        result = detect_prompt(buf)
        # Trailing whitespace before prompt is ignored; the match is the prompt itself
        assert result == "<H3C>"

    def test_system_view(self):
        buf = "\r\n[H3C]"
        assert detect_prompt(buf) == "[H3C]"

    def test_system_view_renamed(self):
        buf = "\r\n[CoreRouter]"
        assert detect_prompt(buf) == "[CoreRouter]"

    def test_interface_view(self):
        buf = "\r\n[H3C-GigabitEthernet1/0/1]"
        assert detect_prompt(buf) == "[H3C-GigabitEthernet1/0/1]"

    def test_interface_view_ten_gig(self):
        buf = "\r\n[H3C-Ten-GigabitEthernet1/0/24]"
        assert detect_prompt(buf) == "[H3C-Ten-GigabitEthernet1/0/24]"

    def test_vlan_view(self):
        buf = "\r\n[H3C-Vlan-interface10]"
        assert detect_prompt(buf) == "[H3C-Vlan-interface10]"

    def test_more_prompt(self):
        buf = "\r\n  ---- More ----\r\n"
        assert detect_prompt(buf) == "---- More ----"

    def test_more_prompt_compact(self):
        buf = "output text\r\n---- More ----"
        assert detect_prompt(buf) == "---- More ----"

    def test_no_prompt(self):
        assert detect_prompt("some random output") is None

    def test_empty_buffer(self):
        assert detect_prompt("") is None

    def test_returns_last_prompt(self):
        buf = "\r\n<H3C>\r\ndisplay version\r\n<H3C>"
        assert detect_prompt(buf) == "<H3C>"

    def test_mixed_prompts_last_wins(self):
        buf = "<H3C>\r\n[H3C]\r\n[H3C-GigabitEthernet1/0/1]"
        assert detect_prompt(buf) == "[H3C-GigabitEthernet1/0/1]"


class TestNormalizePrompt:
    """Prompt normalization."""

    def test_strips_whitespace(self):
        assert normalize_prompt("<H3C>   ") == "<H3C>"

    def test_no_change_clean(self):
        assert normalize_prompt("<H3C>") == "<H3C>"

    def test_system_view(self):
        assert normalize_prompt("[H3C]\n") == "[H3C]"


class TestIsMorePrompt:
    """Pagination detection."""

    def test_more_with_ctrl_c_hint(self):
        buf = "  ---- More ---- Press Ctrl+C to break\r\n"
        assert is_more_prompt(buf) is True

    def test_more_standard(self):
        buf = "output\r\n  ---- More ----\r\n"
        assert is_more_prompt(buf) is True

    def test_not_more(self):
        buf = "\r\n<H3C>"
        assert is_more_prompt(buf) is False

    def test_not_more_empty(self):
        assert is_more_prompt("") is False


class TestIsLoginPrompt:
    """Login/password prompt detection."""

    def test_login(self):
        assert is_login_prompt("login: ") is True

    def test_username(self):
        assert is_login_prompt("Username: ") is True

    def test_password(self):
        assert is_login_prompt("Password: ") is True

    def test_password_no_space(self):
        assert is_login_prompt("Password:") is True

    def test_not_login(self):
        assert is_login_prompt("<H3C>") is False

    def test_login_embedded(self):
        buf = "Welcome to H3C\r\nlogin: "
        assert is_login_prompt(buf) is True


class TestIsUserView:
    """User view detection."""

    def test_user_view(self):
        assert is_user_view("<H3C>") is True

    def test_not_user_view(self):
        assert is_user_view("[H3C]") is False

    def test_not_user_view_more(self):
        assert is_user_view("---- More ----") is False


class TestIsSystemView:
    """System view detection."""

    def test_system_view(self):
        assert is_system_view("[H3C]") is True

    def test_interface_view_is_system(self):
        assert is_system_view("[H3C-GigabitEthernet1/0/1]") is True

    def test_not_system_view(self):
        assert is_system_view("<H3C>") is False


class TestExtractSysname:
    """Sysname extraction from prompts."""

    def test_user_view(self):
        assert extract_sysname("<H3C>") == "H3C"

    def test_system_view(self):
        assert extract_sysname("[H3C]") == "H3C"

    def test_interface_view(self):
        assert extract_sysname("[CoreSwitch-GigabitEthernet1/0/1]") == "CoreSwitch"

    def test_renamed_user(self):
        assert extract_sysname("<MyRouter>") == "MyRouter"

    def test_no_prompt(self):
        assert extract_sysname("random text") is None

    def test_sysname_with_hyphen(self):
        # Some sysnames legitimately contain hyphens
        # e.g. [Core-DC1-GigabitEthernet1/0/1] — sysname is "Core-DC1"
        # This is an edge case: we extract up to the first hyphen,
        # which may not be correct for hyphenated sysnames.
        # This is a known limitation.
        result = extract_sysname("[DC1-Core-GigabitEthernet1/0/1]")
        assert result == "DC1"  # Known limitation
