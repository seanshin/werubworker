"""HMAC-SHA256 signing and verification for webhooks.

Provides request-level HMAC signatures for outbound webhooks and
verification of inbound webhook signatures. Each consumer (receiver)
gets an isolated secret to limit blast radius if one is compromised.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def generate_secret(nbytes: int = 32) -> str:
    """Generate a URL-safe webhook secret."""
    return secrets.token_urlsafe(nbytes)


def sign_payload(
    payload: bytes | str | dict[str, Any],
    secret: str,
    *,
    algorithm: str = "sha256",
) -> str:
    """Compute HMAC signature for a webhook payload.

    Args:
        payload: Raw bytes, string, or dict (auto-serialized to JSON).
        secret: The shared secret for this consumer.
        algorithm: Hash algorithm (default sha256).

    Returns:
        Hex-encoded HMAC signature.
    """
    if isinstance(payload, dict):
        payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        payload,
        getattr(hashlib, algorithm),
    ).hexdigest()


def verify_signature(
    payload: bytes | str | dict[str, Any],
    secret: str,
    signature: str,
    *,
    algorithm: str = "sha256",
) -> bool:
    """Verify an HMAC signature against the expected value.

    Uses constant-time comparison to prevent timing attacks.
    """
    expected = sign_payload(payload, secret, algorithm=algorithm)
    return hmac.compare_digest(expected, signature)


def build_webhook_headers(
    payload: bytes | str | dict[str, Any],
    secret: str,
    event_id: str | None = None,
    event_type: str = "",
) -> dict[str, str]:
    """Build standard webhook headers including HMAC signature.

    Returns headers dict with:
        X-Signature-256: sha256=<hex>
        X-Event-Id: <uuid> (for idempotent processing)
        X-Event-Type: <type>
        X-Timestamp: <unix epoch>
    """
    sig = sign_payload(payload, secret)
    headers: dict[str, str] = {
        "X-Signature-256": f"sha256={sig}",
        "X-Event-Id": event_id or secrets.token_hex(16),
        "X-Timestamp": str(int(time.time())),
    }
    if event_type:
        headers["X-Event-Type"] = event_type
    return headers


def verify_webhook_headers(
    payload: bytes | str | dict[str, Any],
    secret: str,
    headers: dict[str, str],
    *,
    max_age_seconds: int = 300,
) -> tuple[bool, str]:
    """Verify incoming webhook headers.

    Checks:
        1. X-Signature-256 matches
        2. X-Timestamp is within max_age_seconds (replay protection)

    Returns:
        (valid, error_message)
    """
    sig_header = headers.get("X-Signature-256", "")
    if not sig_header.startswith("sha256="):
        return False, "Missing or malformed X-Signature-256 header"

    signature = sig_header[len("sha256="):]
    if not verify_signature(payload, secret, signature):
        return False, "Signature mismatch"

    ts_str = headers.get("X-Timestamp", "")
    if ts_str:
        try:
            ts = int(ts_str)
            age = abs(time.time() - ts)
            if age > max_age_seconds:
                return False, f"Timestamp too old ({int(age)}s > {max_age_seconds}s)"
        except ValueError:
            return False, "Invalid X-Timestamp"

    return True, ""
