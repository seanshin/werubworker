"""Local authentication tests."""

from __future__ import annotations

import time

from coworker.auth import LocalAuth


def test_auth_not_configured(tmp_path):
    """When no password is set, verify() always returns True (pass-through)."""
    auth = LocalAuth(tmp_path)
    assert auth.verify() is True
    assert auth.verify("any-token") is True
    status = auth.status()
    assert status["configured"] is False
    assert status["locked"] is False


def test_auth_setup_and_login(tmp_path):
    auth = LocalAuth(tmp_path)

    # Setup
    token = auth.setup("mypassword")
    assert isinstance(token, str)
    assert len(token) > 10

    # Verify with the issued token
    assert auth.verify(token) is True

    # Without token, should fail
    assert auth.verify() is False
    assert auth.verify("wrong-token") is False

    # Login with correct password
    token2 = auth.login("mypassword")
    assert auth.verify(token2) is True

    # Status should show configured
    status = auth.status()
    assert status["configured"] is True


def test_auth_setup_duplicate(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("password1")
    try:
        auth.setup("password2")
        assert False, "Should raise ValueError for duplicate setup"
    except ValueError as e:
        assert "already configured" in str(e).lower()


def test_auth_setup_short_password(tmp_path):
    auth = LocalAuth(tmp_path)
    try:
        auth.setup("abc")
        assert False, "Should raise ValueError for short password"
    except ValueError:
        pass


def test_auth_wrong_password(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("correct_password")
    try:
        auth.login("wrong_password")
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "incorrect" in str(e).lower()


def test_auth_login_no_password_set(tmp_path):
    auth = LocalAuth(tmp_path)
    try:
        auth.login("anything")
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "no password" in str(e).lower()


def test_auth_session_expiry(tmp_path):
    auth = LocalAuth(tmp_path)
    token = auth.setup("password")

    # Token should be valid now
    assert auth.verify(token) is True

    # Simulate expired session by manipulating the issued-at time
    auth._token_issued_at = time.time() - 7200  # 2 hours ago
    assert auth.verify(token) is False


def test_auth_change_password(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("old_password")

    # Change password
    new_token = auth.change_password("old_password", "new_password")
    assert isinstance(new_token, str)

    # Old password should fail
    try:
        auth.login("old_password")
        assert False, "Old password should no longer work"
    except ValueError:
        pass

    # New password should work
    token = auth.login("new_password")
    assert auth.verify(token) is True


def test_auth_change_password_wrong_old(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("real_password")
    try:
        auth.change_password("wrong", "new")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_auth_change_password_short_new(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("real_password")
    try:
        auth.change_password("real_password", "ab")
        assert False, "Should raise ValueError"
    except ValueError:
        pass


def test_auth_logout(tmp_path):
    auth = LocalAuth(tmp_path)
    token = auth.setup("password")
    assert auth.verify(token) is True

    auth.logout()
    assert auth.verify(token) is False

    # Can login again
    token2 = auth.login("password")
    assert auth.verify(token2) is True


def test_auth_persistence(tmp_path):
    """Auth state should persist to disk and survive reloads."""
    auth1 = LocalAuth(tmp_path)
    auth1.setup("persistent_pw")

    # Reload from disk
    auth2 = LocalAuth(tmp_path)
    status = auth2.status()
    assert status["configured"] is True

    # Login should work with the new instance
    token = auth2.login("persistent_pw")
    assert auth2.verify(token) is True


def test_auth_set_lock_timeout(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("password")
    auth.set_lock_timeout(300)
    assert auth.status()["lock_timeout"] == 300


def test_auth_set_lock_timeout_too_short(tmp_path):
    auth = LocalAuth(tmp_path)
    auth.setup("password")
    try:
        auth.set_lock_timeout(30)
        assert False, "Should raise ValueError"
    except ValueError:
        pass
