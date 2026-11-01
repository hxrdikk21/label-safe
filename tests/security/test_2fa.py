"""
Security Unit Test Suite for Two-Factor Authentication (Phase 5).
Tests RFC 6238 TOTP secret generation, token verification, window tolerance, and backup codes.
"""

import time

from src.labelsafe.auth.two_factor import (
    generate_backup_codes,
    generate_totp_code,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
)


class TestTwoFactorAuthentication:
    """Tests for RFC 6238 TOTP 2FA engine."""

    def test_generate_secret_and_code(self):
        secret = generate_totp_secret()
        assert len(secret) >= 16

        code = generate_totp_code(secret)
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_totp_code_success(self):
        secret = generate_totp_secret()
        code = generate_totp_code(secret)

        assert verify_totp_code(secret, code) is True

    def test_verify_totp_code_failure(self):
        secret = generate_totp_secret()
        assert verify_totp_code(secret, "000000") is False
        assert verify_totp_code(secret, "abcdef") is False
        assert verify_totp_code(secret, "") is False

    def test_totp_window_drift_tolerance(self):
        secret = generate_totp_secret()
        now = int(time.time())

        # Generate code from 30 seconds ago (1 interval back)
        past_code = generate_totp_code(secret, timestamp=now - 30)

        # Window=1 should accept past code within 30s
        assert verify_totp_code(secret, past_code, window=1, timestamp=now) is True

        # Window=0 should reject past code
        assert verify_totp_code(secret, past_code, window=0, timestamp=now) is False

        # Code from 90 seconds ago (3 intervals back) should fail with window=1
        ancient_code = generate_totp_code(secret, timestamp=now - 90)
        assert verify_totp_code(secret, ancient_code, window=1, timestamp=now) is False

    def test_totp_uri_formatting(self):
        secret = "JBSWY3DPEHPK3PXP"
        uri = get_totp_uri(secret, account_name="dr.smith@hospital.org", issuer="LabelSafe")
        assert uri.startswith("otpauth://totp/LabelSafe:")
        assert "secret=JBSWY3DPEHPK3PXP" in uri
        assert "period=30" in uri

    def test_generate_backup_codes(self):
        codes = generate_backup_codes(count=8)
        assert len(codes) == 8
        for c in codes:
            assert len(c) == 9  # XXXX-XXXX format
            assert "-" in c
