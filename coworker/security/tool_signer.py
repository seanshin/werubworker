"""HMAC signing for high-risk MCP tool invocations.

Provides non-repudiation for dangerous operations by generating a signed
audit record for each invocation. The signature covers the tool name,
arguments, caller identity, and timestamp — proving who invoked what and when.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from .hmac_signer import sign_payload


# Default signing secret — should be overridden from config/secrets
_DEFAULT_SECRET = "werubworker-tool-sign-default"

# Tools that require signed invocation records
HIGH_RISK_TOOLS = frozenset({
    "ssh_execute", "ssh_sudo",
    "docker_restart", "docker_stop", "docker_remove",
    "k8s_scale", "k8s_delete",
    "db_query", "db_write",
    "server_reboot", "server_shutdown",
    "secret_access", "secret_put", "secret_delete",
    "cert_revoke",
    "backup_restore",
    "firewall_modify",
})


def sign_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    caller: str = "",
    session_id: str = "",
    secret: Optional[str] = None,
) -> dict[str, Any]:
    """Create a signed record for a tool invocation.

    Args:
        tool_name: Name of the tool being invoked.
        arguments: Tool arguments (sensitive values should be pre-filtered).
        caller: Identity of the caller (user/agent).
        session_id: Current session ID.
        secret: HMAC secret (defaults to built-in key).

    Returns:
        Signed record dict with signature, timestamp, and metadata.
    """
    ts = time.time()
    record = {
        "tool": tool_name,
        "args_hash": _hash_args(arguments),
        "caller": caller,
        "session_id": session_id,
        "timestamp": ts,
    }

    payload = json.dumps(record, separators=(",", ":"), sort_keys=True)
    signature = sign_payload(payload, secret or _DEFAULT_SECRET)

    record["signature"] = signature
    return record


def verify_tool_call(
    record: dict[str, Any],
    secret: Optional[str] = None,
) -> bool:
    """Verify a signed tool call record.

    Returns True if the signature is valid.
    """
    sig = record.get("signature", "")
    # Reconstruct the payload without the signature
    check = {k: v for k, v in record.items() if k != "signature"}
    payload = json.dumps(check, separators=(",", ":"), sort_keys=True)
    expected = sign_payload(payload, secret or _DEFAULT_SECRET)
    import hmac
    return hmac.compare_digest(expected, sig)


def is_high_risk(tool_name: str) -> bool:
    """Check if a tool requires signed invocation."""
    return tool_name in HIGH_RISK_TOOLS


def _hash_args(args: dict[str, Any]) -> str:
    """Create a deterministic hash of tool arguments."""
    import hashlib
    payload = json.dumps(args, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
