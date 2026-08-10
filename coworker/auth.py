"""Local master password authentication for WeruBWorker.

Provides PBKDF2-SHA256 password hashing, session tokens with configurable auto-lock
timeout, and a pass-through mode when no password is configured (existing installs
keep working with zero friction).
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
        return self._issue_token()

    def verify(self, token: Optional[str] = None) -> bool:
        """Return whether the caller is authenticated.

        - No password configured → always ``True`` (pass-through).
        - Password configured but no token → ``False``.
        - Valid, non-expired token → ``True``.
        """
        if not self._state.get("hash"):
            return True  # pass-through: no auth configured
        if not token or not self._token:
            return False
        if not secrets.compare_digest(token, self._token):
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

    def status(self) -> dict:
        """Public status blob (safe to expose to unauthenticated callers)."""
        configured = bool(self._state.get("hash"))
        locked = configured and not self.verify(self._token)
        return {
            "configured": configured,
            "locked": locked,
            "lock_timeout": self._state.get("lock_timeout", _DEFAULT_LOCK_TIMEOUT),
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

    def _issue_token(self) -> str:
        self._token = secrets.token_urlsafe(_TOKEN_BYTES)
        self._token_issued_at = time.time()
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
