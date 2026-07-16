"""Tests for sensitive data redaction."""

from __future__ import annotations

import pytest

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

    @pytest.mark.parametrize(
        "text, secret",
        [
            (
                "super password role network-admin hash SUPER_HASH_SECRET",
                "SUPER_HASH_SECRET",
            ),
            (
                "super password role level-15 cipher SUPER_CIPHER_SECRET",
                "SUPER_CIPHER_SECRET",
            ),
            ("super password simple SUPER_SIMPLE_SECRET", "SUPER_SIMPLE_SECRET"),
            (
                "SUPER   PASSWORD   ROLE   NETWORK-ADMIN   CiPhEr   MIXED_SUPER_SECRET",
                "MIXED_SUPER_SECRET",
            ),
        ],
    )
    @pytest.mark.parametrize("redactor", [redact_sensitive, quick_redact])
    def test_super_password_line_is_fully_redacted(
        self,
        text: str,
        secret: str,
        redactor,
    ) -> None:
        result = redactor(text)

        assert secret not in result
        assert "role" not in result.casefold()
        assert "hash" not in result.casefold()
        assert "cipher" not in result.casefold()
        assert "simple" not in result.casefold()
        assert result == "super password *** REDACTED ***"


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

    @pytest.mark.parametrize(
        "text, secret",
        [
            ("snmp-agent community read cipher CIPHERTEXT_SNMP", "CIPHERTEXT_SNMP"),
            ("snmp-agent community write simple PRIVATE_COMMUNITY", "PRIVATE_COMMUNITY"),
            ("SNMP-AGENT COMMUNITY READ CiPhEr MIXED_CASE_SECRET", "MIXED_CASE_SECRET"),
        ],
    )
    def test_snmp_community_qualifier_does_not_leave_real_secret(
        self,
        text: str,
        secret: str,
    ) -> None:
        result = redact_sensitive(text)
        assert secret not in result
        assert "cipher" not in result.casefold()
        assert "simple" not in result.casefold()


class TestComwareAuthenticationLineRedaction:
    """Credential syntax families must redact the secret after qualifiers."""

    @pytest.mark.parametrize(
        "text, secret",
        [
            (
                "ntp-service authentication-keyid 1 authentication-mode md5 cipher NTP_CIPHER_SECRET",
                "NTP_CIPHER_SECRET",
            ),
            (
                "ntp-service authentication-keyid 2 authentication-mode sha simple NTP_SIMPLE_SECRET",
                "NTP_SIMPLE_SECRET",
            ),
            (
                "NTP-SERVICE AUTHENTICATION-KEYID 3 AUTHENTICATION-MODE SHA256 NTP_PLAIN_SECRET",
                "NTP_PLAIN_SECRET",
            ),
            ("key authentication cipher RADIUS_AUTH_SECRET", "RADIUS_AUTH_SECRET"),
            ("key accounting simple RADIUS_ACCT_SECRET", "RADIUS_ACCT_SECRET"),
            ("KEY AUTHENTICATION SIMPLE TACACS_AUTH_SECRET", "TACACS_AUTH_SECRET"),
            ("Key Accounting Cipher TACACS_ACCT_SECRET", "TACACS_ACCT_SECRET"),
        ],
    )
    def test_qualified_secret_is_fully_removed(self, text: str, secret: str) -> None:
        result = redact_sensitive(text)
        assert secret not in result
        assert "***" in result

    def test_multiple_credentials_on_one_line_are_all_removed(self) -> None:
        text = "key authentication cipher FIRST_SECRET key accounting simple SECOND_SECRET"
        result = redact_sensitive(text)
        assert "FIRST_SECRET" not in result
        assert "SECOND_SECRET" not in result
        assert "***" in result

    @pytest.mark.parametrize(
        "redactor",
        [redact_sensitive, quick_redact],
    )
    def test_fast_and_full_redaction_cover_comware_credential_families(self, redactor) -> None:
        text = (
            "snmp-agent community read cipher SNMP_SECRET\n"
            "ntp-service authentication-keyid 1 authentication-mode md5 cipher NTP_SECRET\n"
            "key authentication cipher AAA_SECRET"
        )
        result = redactor(text)
        assert "SNMP_SECRET" not in result
        assert "NTP_SECRET" not in result
        assert "AAA_SECRET" not in result

    def test_snmpv3_auth_and_privacy_secrets(self) -> None:
        text = (
            "snmp-agent usm-user v3 netops group1 authentication-mode sha auth-secret "
            "privacy-mode aes128 priv-secret"
        )

        result = redact_sensitive(text)

        assert "auth-secret" not in result
        assert "priv-secret" not in result
        assert result == "snmp-agent usm-user *** REDACTED ***"


class TestPrivateKeyRedaction:
    @pytest.mark.parametrize(
        "label",
        ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY", "ENCRYPTED PRIVATE KEY"],
    )
    def test_complete_private_key_blocks(self, label: str) -> None:
        text = f"before\n-----BEGIN {label}-----\nvery-secret-key\n-----END {label}-----\nafter"

        result = redact_sensitive(text)

        assert "very-secret-key" not in result
        assert "BEGIN" not in result
        assert result == "before\n*** PRIVATE MATERIAL REDACTED ***\nafter"

    def test_truncated_private_key_block(self) -> None:
        text = "before\n-----BEGIN OPENSSH PRIVATE KEY-----\ntruncated-secret"

        result = redact_sensitive(text)

        assert "truncated-secret" not in result
        assert result == "before\n*** PRIVATE MATERIAL REDACTED ***"


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

    @pytest.mark.parametrize(
        "label",
        ["PRIVATE KEY", "RSA PRIVATE KEY", "OPENSSH PRIVATE KEY", "EC PRIVATE KEY"],
    )
    def test_existing_private_key_redaction_remains_fail_closed(self, label: str) -> None:
        text = f"-----BEGIN {label}-----\nPRIVATE_MATERIAL\n-----END {label}-----"
        result = redact_sensitive(text)
        assert "PRIVATE_MATERIAL" not in result
        assert "BEGIN" not in result


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
