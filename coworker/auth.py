"""Local master password authentication for WeruBWorker.

Provides PBKDF2-SHA256 password hashing, session tokens with configurable auto-lock
timeout, optional TOTP two-factor authentication, and a pass-through mode when no
password is configured (existing installs keep working with zero friction).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 32
_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) → 43-char URL-safe string
_DEFAULT_LOCK_TIMEOUT = 30 * 60  # 30 minutes
_MAX_LOGIN_FAILURES = 5
_LOCKOUT_DURATION = 5 * 60  # 5 minutes

# Actions that require step-up re-authentication when 2FA is enabled
_STEP_UP_ACTIONS = frozenset({
    "ssh_execute", "docker_restart", "db_write",
    "secret_access", "k8s_scale", "server_reboot",
})
_STEP_UP_WINDOW = 5 * 60  # 5 minutes — re-auth valid for this period


class LocalAuth:
    """Disk-backed master password gate.

    State lives in ``<data_dir>/auth.json`` (0600).  When no password has been
    configured, *verify()* returns ``True`` unconditionally so the rest of the
    stack never needs to branch on "auth might not exist".
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "auth.json"
        self._state = self._load()
        # Live session — never persisted to disk.
        self._token: Optional[str] = None
        self._token_issued_at: float = 0.0
        self._step_up_at: float = 0.0  # last step-up re-auth timestamp

    # -- public API -----------------------------------------------------------

    def setup(self, password: str) -> str:
        """Set the master password for the first time.  Returns a session token."""
        if self._state.get("hash"):
            raise ValueError("Password already configured; use change_password().")
        if not password or len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")
        salt = os.urandom(_SALT_BYTES)
        h = self._hash(password, salt)
        self._state = {
            "hash": h.hex(),
            "salt": salt.hex(),
            "iterations": _PBKDF2_ITERATIONS,
            "lock_timeout": _DEFAULT_LOCK_TIMEOUT,
        }
        self._save()
        return self._issue_token()

    def login(self, password: str) -> str:
        """Verify *password* and return a session token.  Raises on failure.

        After *_MAX_LOGIN_FAILURES* consecutive wrong passwords the account is
        locked for *_LOCKOUT_DURATION* seconds.  The failure counter and last
        failure timestamp are persisted in auth.json so a restart doesn't reset
        the lockout.
        """
        if not self._state.get("hash"):
            raise ValueError("No password configured.")

        # -- lockout check -------------------------------------------------------
        fail_count = self._state.get("login_fail_count", 0)
        last_fail = self._state.get("login_fail_time", 0.0)
        if fail_count >= _MAX_LOGIN_FAILURES:
            elapsed = time.time() - last_fail
            if elapsed < _LOCKOUT_DURATION:
                remaining = int(_LOCKOUT_DURATION - elapsed) + 1
                raise ValueError(
                    f"Account locked after {_MAX_LOGIN_FAILURES} failed attempts. "
                    f"Try again in {remaining}s."
                )
            # Lockout expired — reset counters before proceeding.
            self._state["login_fail_count"] = 0
            self._state["login_fail_time"] = 0.0
            self._save()

        # -- password verification ------------------------------------------------
        if not self._check(password):
            self._state["login_fail_count"] = self._state.get("login_fail_count", 0) + 1
            self._state["login_fail_time"] = time.time()
            self._save()
            raise ValueError("Incorrect password.")

        # Success — clear any accumulated failures.
        if self._state.get("login_fail_count", 0) > 0:
            self._state["login_fail_count"] = 0
            self._state["login_fail_time"] = 0.0
            self._save()

        # If 2FA is enabled, password alone is not enough — return pending token
        if self._state.get("totp_secret"):
            return self._issue_token(pending_2fa=True)
        return self._issue_token()

    def verify(self, token: Optional[str] = None) -> bool:
        """Return whether the caller is authenticated.

        - No password configured → always ``True`` (pass-through).
        - Password configured but no token → ``False``.
        - Valid, non-expired token → ``True``.
        - 2FA pending token → ``False`` (must complete verify_totp first).
        """
        if not self._state.get("hash"):
            return True  # pass-through: no auth configured
        if not token or not self._token:
            return False
        if not secrets.compare_digest(token, self._token):
            return False
        # Reject pending-2FA tokens
        if getattr(self, "_pending_2fa", False):
            return False
        timeout = self._state.get("lock_timeout", _DEFAULT_LOCK_TIMEOUT)
        if time.time() - self._token_issued_at > timeout:
            self._token = None
            return False
        return True

    def logout(self) -> None:
        """Invalidate the current session token."""
        self._token = None

    def change_password(self, old_password: str, new_password: str) -> str:
        """Change the master password.  Returns a fresh session token."""
        if not self._state.get("hash"):
            raise ValueError("No password configured; use setup().")
        if not self._check(old_password):
            raise ValueError("Incorrect current password.")
        if not new_password or len(new_password) < 4:
            raise ValueError("New password must be at least 4 characters.")
        salt = os.urandom(_SALT_BYTES)
        h = self._hash(new_password, salt)
        self._state["hash"] = h.hex()
        self._state["salt"] = salt.hex()
        self._save()
        return self._issue_token()

    def set_lock_timeout(self, seconds: int) -> None:
        """Update the auto-lock timeout (in seconds)."""
        if seconds < 60:
            raise ValueError("Lock timeout must be at least 60 seconds.")
        self._state["lock_timeout"] = seconds
        self._save()

    # -- TOTP 2FA ----------------------------------------------------------------

    def setup_totp(self, account: str = "admin") -> dict:
        """Enable TOTP 2FA. Returns secret, provisioning URI, and backup codes.

        Must be called while authenticated. The secret is persisted in auth.json.
        """
        from .security.totp import generate_backup_codes, generate_secret, get_provisioning_uri

        secret = generate_secret()
        backup_codes = generate_backup_codes()
        self._state["totp_secret"] = secret
        self._state["totp_backup_codes"] = backup_codes
        self._save()
        return {
            "secret": secret,
            "provisioning_uri": get_provisioning_uri(secret, account),
            "backup_codes": backup_codes,
        }

    def verify_totp(self, code: str) -> str:
        """Verify a TOTP code and upgrade a pending-2FA token to a full session.

        Also accepts one-time backup codes for recovery.
        Returns a full session token on success.
        """
        totp_secret = self._state.get("totp_secret")
        if not totp_secret:
            raise ValueError("TOTP is not configured.")
        if not getattr(self, "_pending_2fa", False):
            raise ValueError("No pending 2FA login.")

        # Try backup code first
        backup_codes = self._state.get("totp_backup_codes", [])
        if code in backup_codes:
            backup_codes.remove(code)
            self._state["totp_backup_codes"] = backup_codes
            self._save()
            self._pending_2fa = False
            return self._token  # type: ignore[return-value]

        # Verify TOTP code
        from .security.totp import verify_code

        if not verify_code(totp_secret, code):
            raise ValueError("Invalid TOTP code.")

        self._pending_2fa = False
        return self._token  # type: ignore[return-value]

    def disable_totp(self, password: str) -> None:
        """Disable TOTP 2FA. Requires current password for confirmation."""
        if not self._check(password):
            raise ValueError("Incorrect password.")
        self._state.pop("totp_secret", None)
        self._state.pop("totp_backup_codes", None)
        self._save()

    def totp_enabled(self) -> bool:
        """Check if TOTP 2FA is enabled."""
        return bool(self._state.get("totp_secret"))

    def verify_step_up(self, action: str) -> bool:
        """Check if a step-up re-authentication is required for an action.

        Returns True if the action is allowed (no step-up needed or within window).
        Returns False if step-up re-authentication is required.
        """
        if not self._state.get("totp_secret"):
            return True  # No 2FA → no step-up
        if action not in _STEP_UP_ACTIONS:
            return True  # Not a sensitive action
        if time.time() - self._step_up_at < _STEP_UP_WINDOW:
            return True  # Within step-up window
        return False

    def step_up(self, code: str) -> bool:
        """Perform step-up re-authentication with a TOTP code.

        Returns True if the code is valid. Refreshes the step-up window.
        """
        totp_secret = self._state.get("totp_secret")
        if not totp_secret:
            return True  # No 2FA configured

        from .security.totp import verify_code

        if verify_code(totp_secret, code):
            self._step_up_at = time.time()
            return True
        return False

    def status(self) -> dict:
        """Public status blob (safe to expose to unauthenticated callers)."""
        configured = bool(self._state.get("hash"))
        locked = configured and not self.verify(self._token)
        return {
            "configured": configured,
            "locked": locked,
            "lock_timeout": self._state.get("lock_timeout", _DEFAULT_LOCK_TIMEOUT),
            "totp_enabled": self.totp_enabled(),
        }

    # -- internals ------------------------------------------------------------

    def _hash(self, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            self._state.get("iterations", _PBKDF2_ITERATIONS),
        )

    def _check(self, password: str) -> bool:
        stored = bytes.fromhex(self._state["hash"])
        salt = bytes.fromhex(self._state["salt"])
        candidate = self._hash(password, salt)
        return secrets.compare_digest(candidate, stored)

    def _issue_token(self, *, pending_2fa: bool = False) -> str:
        self._token = secrets.token_urlsafe(_TOKEN_BYTES)
        self._token_issued_at = time.time()
        self._pending_2fa = pending_2fa
        return self._token

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state, indent=2))
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # Windows or other restrictive FS
