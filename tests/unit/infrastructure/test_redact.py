"""Tests for sensitive data redaction."""

from __future__ import annotations

from h3c_hcl_mcp.infrastructure.audit.redact import (
    quick_redact,
    redact_sensitive,
)


class TestPasswordRedaction:
    """Password and secret patterns must be redacted."""

    def test_simple_password_redacted(self) -> None:
        text = "password simple admin123"
        result = redact_sensitive(text)
        assert "admin123" not in result
        assert "***" in result

    def test_cipher_password_redacted(self) -> None:
        text = "password cipher $c$3$abcdef123456"
        result = redact_sensitive(text)
        assert "$c$3$abcdef123456" not in result
        assert "***" in result

    def test_hash_password_redacted(self) -> None:
        text = "password hash SHA256:abcdef1234567890"
        result = redact_sensitive(text)
        assert "SHA256:abcdef1234567890" not in result
        assert "***" in result

    def test_set_password_redacted(self) -> None:
        text = "set password mysecretpass"
        result = redact_sensitive(text)
        assert "mysecretpass" not in result
        assert "***" in result

    def test_secret_redacted(self) -> None:
        text = "secret supersecret123"
        result = redact_sensitive(text)
        assert "supersecret123" not in result
        assert "secret ***" in result


class TestSNMPRedaction:
    """SNMP community strings and credentials must be redacted."""

    def test_snmp_read_community(self) -> None:
        text = "snmp-agent community read public123"
        result = redact_sensitive(text)
        assert "public123" not in result
        assert "***" in result

    def test_snmp_write_community(self) -> None:
        text = "snmp-agent community write private456"
        result = redact_sensitive(text)
        assert "private456" not in result
        assert "***" in result

    def test_snmp_no_qualifier_community(self) -> None:
        text = "snmp-agent community mystring"
        result = redact_sensitive(text)
        assert "mystring" not in result
        assert "***" in result


class TestLocalUserRedaction:
    """Local user passwords must be redacted."""

    def test_local_user_password_simple(self) -> None:
        text = "local-user admin password simple admin123"
        result = redact_sensitive(text)
        assert "admin123" not in result
        assert "***" in result

    def test_local_user_password_cipher(self) -> None:
        text = "local-user netadmin password cipher $c$3$abcdef"
        result = redact_sensitive(text)
        assert "$c$3$abcdef" not in result
        assert "***" in result


class TestKeyRedaction:
    """Pre-shared keys and authentication keys must be redacted."""

    def test_preshared_key(self) -> None:
        text = "pre-shared-key simple vpnsecret123"
        result = redact_sensitive(text)
        assert "vpnsecret123" not in result
        assert "***" in result

    def test_authentication_key(self) -> None:
        text = "authentication-key simple myauthkey"
        result = redact_sensitive(text)
        assert "myauthkey" not in result
        assert "***" in result

    def test_key_simple(self) -> None:
        text = "key simple mykeyvalue"
        result = redact_sensitive(text)
        assert "mykeyvalue" not in result
        assert "***" in result


class TestNonSensitivePreservation:
    """Non-sensitive configuration should be preserved."""

    def test_interface_config_preserved(self) -> None:
        text = "interface GigabitEthernet 1/0/1\n port link-type trunk\n port trunk permit vlan 1 10 20"
        result = redact_sensitive(text)
        assert "interface GigabitEthernet 1/0/1" in result
        assert "port link-type trunk" in result
        assert "vlan 1 10 20" in result

    def test_display_version_preserved(self) -> None:
        text = "H3C Comware Software, Version 7.1.064, Release 5435"
        result = redact_sensitive(text)
        assert text == result

    def test_routing_table_preserved(self) -> None:
        text = "1.1.1.0/24 Direct 0 0 1.1.1.1 Vlan-interface1"
        result = redact_sensitive(text)
        assert text == result

    def test_system_info_preserved(self) -> None:
        text = "sysname H3C-Core-01\n hardware-speed 1000"
        result = redact_sensitive(text)
        assert "sysname H3C-Core-01" in result
        assert "hardware-speed 1000" in result

    def test_empty_string(self) -> None:
        assert redact_sensitive("") == ""

    def test_none_like_calls(self) -> None:
        """quick_redact handles empty string."""
        assert quick_redact("") == ""


class TestRedactMultiplePatterns:
    """Multiple sensitive patterns in one text should all be redacted."""

    def test_multiple_passwords(self) -> None:
        text = (
            "local-user admin password simple admin123\n"
            "local-user guest password simple guest456\n"
            "snmp-agent community read public789\n"
            "interface GigabitEthernet 1/0/1\n"
            " description Uplink to core"
        )
        result = redact_sensitive(text)
        assert "admin123" not in result
        assert "guest456" not in result
        assert "public789" not in result
        assert "interface GigabitEthernet 1/0/1" in result
        assert "Uplink to core" in result


class TestQuickRedact:
    """quick_redact should handle the most common patterns."""

    def test_quick_redact_password(self) -> None:
        text = "password simple mypass123"
        result = quick_redact(text)
        assert "mypass123" not in result

    def test_quick_redact_secret(self) -> None:
        text = "secret topsecret999"
        result = quick_redact(text)
        assert "topsecret999" not in result

    def test_quick_redact_snmp_community(self) -> None:
        text = "snmp-agent community read public"
        result = quick_redact(text)
        assert "public" not in result
