"""Tests for coworker.security.totp and auth.py 2FA integration."""

import time

import pytest

from coworker.security.totp import (
    generate_backup_codes,
    generate_code,
    generate_secret,
    get_provisioning_uri,
    verify_code,
)
from coworker.auth import LocalAuth


class TestTOTPCore:
    def test_generate_secret_length(self):
        secret = generate_secret()
        assert len(secret) >= 20

    def test_generate_secret_unique(self):
        assert generate_secret() != generate_secret()

    def test_generate_code_format(self):
        secret = generate_secret()
        code = generate_code(secret)
        assert len(code) == 6
        assert code.isdigit()

    def test_code_deterministic(self):
        secret = generate_secret()
        ts = 1234567890.0
        c1 = generate_code(secret, timestamp=ts)
        c2 = generate_code(secret, timestamp=ts)
        assert c1 == c2

    def test_verify_current_code(self):
        secret = generate_secret()
        code = generate_code(secret)
        assert verify_code(secret, code)

    def test_verify_wrong_code(self):
        secret = generate_secret()
        assert not verify_code(secret, "000000")

    def test_verify_with_window(self):
        secret = generate_secret()
        ts = time.time()
        # Code from 30 seconds ago (1 period) should still work with window=1
        code = generate_code(secret, timestamp=ts - 30)
        assert verify_code(secret, code, timestamp=ts, window=1)

    def test_verify_outside_window(self):
        secret = generate_secret()
        ts = time.time()
        # Code from 90 seconds ago (3 periods) should fail with window=1
        code = generate_code(secret, timestamp=ts - 90)
        assert not verify_code(secret, code, timestamp=ts, window=1)

    def test_verify_empty_code(self):
        secret = generate_secret()
        assert not verify_code(secret, "")

    def test_verify_wrong_length(self):
        secret = generate_secret()
        assert not verify_code(secret, "12345")  # 5 digits


class TestBackupCodes:
    def test_count(self):
        codes = generate_backup_codes(10)
        assert len(codes) == 10

    def test_unique(self):
        codes = generate_backup_codes(10)
        assert len(set(codes)) == 10

    def test_format(self):
        codes = generate_backup_codes()
        for code in codes:
            assert len(code) == 8
            assert all(c in "0123456789abcdef" for c in code)


class TestProvisioningUri:
    def test_format(self):
        uri = get_provisioning_uri("JBSWY3DPEHPK3PXP", "admin")
        assert uri.startswith("otpauth://totp/")
        assert "secret=JBSWY3DPEHPK3PXP" in uri
        assert "issuer=WeruBWorker" in uri

    def test_custom_issuer(self):
        uri = get_provisioning_uri("SECRET", "user", issuer="MyApp")
        assert "issuer=MyApp" in uri


class TestAuthTOTPIntegration:
    @pytest.fixture
    def auth(self, tmp_path):
        a = LocalAuth(tmp_path)
        a.setup("password123")
        return a

    def test_totp_not_enabled_by_default(self, auth):
        assert not auth.totp_enabled()
        assert auth.status()["totp_enabled"] is False

    def test_setup_totp(self, auth):
        result = auth.setup_totp("admin")
        assert "secret" in result
        assert "provisioning_uri" in result
        assert "backup_codes" in result
        assert len(result["backup_codes"]) == 10
        assert auth.totp_enabled()

    def test_login_with_2fa(self, auth):
        totp_info = auth.setup_totp()
        auth.logout()

        # Login with password — returns pending token
        token = auth.login("password123")
        # Token is pending 2FA — verify should fail
        assert not auth.verify(token)

        # Complete 2FA with TOTP code
        code = generate_code(totp_info["secret"])
        full_token = auth.verify_totp(code)
        assert auth.verify(full_token)

    def test_login_with_backup_code(self, auth):
        totp_info = auth.setup_totp()
        backup = totp_info["backup_codes"][0]
        auth.logout()

        auth.login("password123")
        full_token = auth.verify_totp(backup)
        assert auth.verify(full_token)

        # Same backup code should not work again
        auth.logout()
        auth.login("password123")
        with pytest.raises(ValueError, match="Invalid TOTP"):
            auth.verify_totp(backup)

    def test_disable_totp(self, auth):
        auth.setup_totp()
        assert auth.totp_enabled()
        auth.disable_totp("password123")
        assert not auth.totp_enabled()

    def test_disable_totp_wrong_password(self, auth):
        auth.setup_totp()
        with pytest.raises(ValueError, match="Incorrect"):
            auth.disable_totp("wrong")

    def test_step_up_no_2fa(self, auth):
        # Without 2FA, step-up always passes
        assert auth.verify_step_up("ssh_execute")

    def test_step_up_required(self, auth):
        auth.setup_totp()
        assert not auth.verify_step_up("ssh_execute")
        assert auth.verify_step_up("normal_action")

    def test_step_up_with_code(self, auth):
        totp_info = auth.setup_totp()
        assert not auth.verify_step_up("ssh_execute")

        code = generate_code(totp_info["secret"])
        assert auth.step_up(code)
        assert auth.verify_step_up("ssh_execute")

    def test_login_without_2fa_unchanged(self, tmp_path):
        """2FA 미설정 시 기존 동작 그대로."""
        auth = LocalAuth(tmp_path)
        token = auth.setup("mypassword")
        assert auth.verify(token)
