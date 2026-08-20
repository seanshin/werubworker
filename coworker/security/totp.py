"""TOTP (Time-based One-Time Password) for two-factor authentication.

Implements RFC 6238 TOTP with:
- Secret generation and QR URI for authenticator app enrollment
- Code generation and verification with configurable time window
- One-time backup codes for recovery
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Optional


_DEFAULT_DIGITS = 6
_DEFAULT_PERIOD = 30  # seconds
_DEFAULT_WINDOW = 1  # +-1 period tolerance
_SECRET_BYTES = 20  # 160-bit secret (standard)
_BACKUP_CODE_COUNT = 10
_BACKUP_CODE_LENGTH = 8


def generate_secret(nbytes: int = _SECRET_BYTES) -> str:
    """Generate a random TOTP secret, base32-encoded."""
    raw = os.urandom(nbytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def generate_backup_codes(count: int = _BACKUP_CODE_COUNT) -> list[str]:
    """Generate one-time backup recovery codes."""
    return [secrets.token_hex(_BACKUP_CODE_LENGTH // 2) for _ in range(count)]


def get_provisioning_uri(
    secret: str,
    account: str,
    issuer: str = "WeruBWorker",
    digits: int = _DEFAULT_DIGITS,
    period: int = _DEFAULT_PERIOD,
) -> str:
    """Build an otpauth:// URI for QR code enrollment.

    Compatible with Google Authenticator, Authy, 1Password, etc.
    """
    from urllib.parse import quote

    label = f"{quote(issuer)}:{quote(account)}"
    params = (
        f"secret={secret}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits={digits}"
        f"&period={period}"
    )
    return f"otpauth://totp/{label}?{params}"


def generate_code(
    secret: str,
    timestamp: Optional[float] = None,
    digits: int = _DEFAULT_DIGITS,
    period: int = _DEFAULT_PERIOD,
) -> str:
    """Generate a TOTP code for the given timestamp (default: now)."""
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // period
    return _hotp(secret, counter, digits)


def verify_code(
    secret: str,
    code: str,
    timestamp: Optional[float] = None,
    digits: int = _DEFAULT_DIGITS,
    period: int = _DEFAULT_PERIOD,
    window: int = _DEFAULT_WINDOW,
) -> bool:
    """Verify a TOTP code with time-window tolerance.

    Checks the current period and +-window adjacent periods
    to account for clock skew.
    """
    if not code or len(code) != digits:
        return False
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // period
    for offset in range(-window, window + 1):
        expected = _hotp(secret, counter + offset, digits)
        if hmac.compare_digest(expected, code):
            return True
    return False


def _hotp(secret: str, counter: int, digits: int) -> str:
    """HOTP algorithm (RFC 4226)."""
    # Decode base32 secret (re-pad if needed)
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)

    # Counter as 8-byte big-endian
    msg = struct.pack(">Q", counter)

    # HMAC-SHA1
    digest = hmac.new(key, msg, hashlib.sha1).digest()

    # Dynamic truncation
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF

    return str(code_int % (10**digits)).zfill(digits)
