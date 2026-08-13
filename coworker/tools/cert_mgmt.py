"""Certificate management tools — SSL monitoring and renewal.

Checks SSL certificate expiry for domains, lists certificates expiring
soon, and triggers Let's Encrypt renewal via ``certbot``.

The ``cert_renew`` tool requires approval as it modifies server state.
"""

from __future__ import annotations

import datetime
import shlex
import socket
import ssl
import subprocess
from typing import Any, Callable

import aisuite as ai


# ---------------------------------------------------------------------------
# SSL check helpers
# ---------------------------------------------------------------------------


def _check_single_cert(domain: str, port: int = 443) -> dict[str, Any]:
    """Check SSL certificate for a single domain."""
    domain = domain.strip()
    if not domain:
        return {"domain": domain, "ok": False, "error": "empty domain"}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()

        if not cert:
            return {"domain": domain, "ok": False, "error": "no certificate returned"}

        # Parse subject
        subject = dict(x[0] for x in cert.get("subject", ()))
        issuer = dict(x[0] for x in cert.get("issuer", ()))
        not_after_str = cert.get("notAfter", "")
        # Python ssl date format: "Mon DD HH:MM:SS YYYY GMT"
        not_after = datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
        now = datetime.datetime.utcnow()
        days_remaining = (not_after - now).days

        if days_remaining < 0:
            status = "expired"
        elif days_remaining <= 7:
            status = "critical"
        elif days_remaining <= 30:
            status = "warning"
        else:
            status = "valid"

        return {
            "domain": domain,
            "ok": True,
            "subject": subject.get("commonName", ""),
            "issuer": issuer.get("organizationName", ""),
            "not_after": not_after.isoformat(),
            "days_remaining": days_remaining,
            "status": status,
        }
    except socket.timeout:
        return {"domain": domain, "ok": False, "error": "connection timed out"}
    except socket.gaierror:
        return {"domain": domain, "ok": False, "error": "DNS resolution failed"}
    except ssl.SSLError as e:
        return {"domain": domain, "ok": False, "error": f"SSL error: {e}"}
    except Exception as e:
        return {"domain": domain, "ok": False, "error": str(e)}


def _cert_check(domains: str) -> dict[str, Any]:
    """Check SSL certificates for multiple domains (comma-separated)."""
    if not domains:
        return {"ok": False, "error": "domains is required (comma-separated list)"}
    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    if not domain_list:
        return {"ok": False, "error": "no valid domains provided"}

    results = [_check_single_cert(d) for d in domain_list]
    return {
        "ok": True,
        "checked": len(results),
        "certificates": results,
    }


def _cert_expiring(days: int = 30) -> dict[str, Any]:
    """List certificates expiring within N days.

    Note: requires a list of domains. In a full deployment this would
    pull from a wiki or configuration source.
    """
    return {
        "ok": False,
        "error": (
            "cert_expiring requires a domain source (wiki or config). "
            "Use cert_check with explicit domains instead."
        ),
    }


def _cert_renew(domain: str, server: str = "") -> dict[str, Any]:
    """Trigger Let's Encrypt certificate renewal via certbot."""
    if not domain:
        return {"ok": False, "error": "domain is required"}

    if server:
        # Remote renewal via SSH
        from ..connectors.ssh.client import SSHClient, SSHServer

        # server format: "user@host:port" or just "host"
        parts = server.split("@")
        if len(parts) == 2:
            username = parts[0]
            host_port = parts[1]
        else:
            username = "deploy"
            host_port = parts[0]

        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 22

        ssh_server = SSHServer(
            server_id=f"certbot-{host}",
            host=host,
            port=port,
            username=username,
        )
        client = SSHClient(ssh_server)
        certbot_cmd = (
            f"sudo certbot renew --cert-name {shlex.quote(domain)} --dry-run"
        )
        result = client.execute(certbot_cmd, timeout=60)
        return {
            "ok": result.get("ok", False),
            "domain": domain,
            "server": server,
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "remote": True,
        }
    else:
        # Local renewal
        try:
            cmd = ["certbot", "renew", "--cert-name", domain, "--dry-run"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return {
                "ok": result.returncode == 0,
                "domain": domain,
                "stdout": result.stdout,
                "stderr": result.stderr.strip() if result.stderr else "",
                "remote": False,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "certbot timed out after 60s"}
        except FileNotFoundError:
            return {"ok": False, "error": "certbot command not found"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_CERT_CHECK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cert_check",
        "description": (
            "Check SSL certificates for one or more domains. "
            "Returns subject, issuer, expiry date, and days remaining."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domains": {
                    "type": "string",
                    "description": "Comma-separated list of domains to check.",
                },
            },
            "required": ["domains"],
        },
    },
}

_CERT_EXPIRING_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cert_expiring",
        "description": "List certificates expiring within N days.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days threshold (default: 30).",
                },
            },
            "required": [],
        },
    },
}

_CERT_RENEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cert_renew",
        "description": (
            "Trigger Let's Encrypt certificate renewal via certbot. "
            "Runs --dry-run by default. Specify server for remote renewal via SSH."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain / cert-name to renew.",
                },
                "server": {
                    "type": "string",
                    "description": (
                        "Remote server for SSH-based renewal "
                        "(format: 'user@host:port' or 'host'). "
                        "Empty for local renewal."
                    ),
                },
            },
            "required": ["domain"],
        },
    },
}


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def cert_mgmt_tools(context: Any = None) -> list:
    """Return certificate management tools."""
    secrets = getattr(context, "secrets", None)
    tools: list[Callable[..., Any]] = []

    def cert_check(domains: str) -> dict:
        """Check SSL certificates for multiple domains."""
        return _cert_check(domains)

    def cert_expiring(days: int = 30) -> dict:
        """List certificates expiring within N days."""
        return _cert_expiring(days)

    def cert_renew(domain: str, server: str = "") -> dict:
        """Trigger Let's Encrypt certificate renewal via certbot."""
        return _cert_renew(domain, server)

    # Metadata
    _read_meta = ai.ToolMetadata(
        category="cert_mgmt",
        risk_level="low",
        capabilities=["cert_mgmt"],
        requires_approval=False,
    )
    _write_meta = ai.ToolMetadata(
        category="cert_mgmt",
        risk_level="medium",
        capabilities=["cert_mgmt"],
        requires_approval=True,
    )

    for fn, schema, meta in [
        (cert_check, _CERT_CHECK_SCHEMA, _read_meta),
        (cert_expiring, _CERT_EXPIRING_SCHEMA, _read_meta),
        (cert_renew, _CERT_RENEW_SCHEMA, _write_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        wrapped.__aisuite_tool_metadata__ = meta
        tools.append(wrapped)

    return tools
