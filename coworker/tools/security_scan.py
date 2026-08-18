"""Security scanning tools — port scan, SSL check, auth log analysis, vulnerability check.

Read-only security tools for verifying firewall rules, SSL certificates, failed login
attempts, pending security updates, and file integrity. All run locally or via SSH.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import socket
import ssl
import subprocess
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

import aisuite as ai


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 30) -> str:
    """Run a command and return stdout (best-effort, never raises)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _ssh_run(secrets: Any, server_id: str, cmd: str, timeout: int = 30) -> dict:
    """Execute a command on a remote server via SSH."""
    from ..connectors.ssh.accounts import get_server as _get_server
    from ..connectors.ssh.client import SSHClient as _SSHClient

    server = _get_server(secrets, server_id)
    if server is None:
        return {"ok": False, "error": f"Server '{server_id}' not found"}
    client = _SSHClient(server)
    return client.execute(cmd, timeout=timeout)


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# Schema helpers (mirrors cloud_infra.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="security_scan",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["security"],
        requires_approval=approval,
    )


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _attach(
    fn: Callable[..., Any],
    schema: dict[str, Any],
    *,
    approval: bool = False,
    caps: list[str] | None = None,
) -> Callable[..., Any]:
    name = schema["function"]["name"]
    fn.__coworker_schema__ = schema
    fn.__aisuite_tool_metadata__ = _meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = schema["function"]["description"]
    fn.__name__ = name
    return fn


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def security_scan_tools(context: Any = None) -> list:
    """Return security scanning tools."""
    secrets = getattr(context, "secrets", None)
    tools: list[Callable[..., Any]] = []

    # -- port_scan --
    def port_scan(
        host: str, ports: str = "22,80,443,3306,5432,6379,8080,8443"
    ) -> dict:
        """TCP 포트 스캔으로 열려 있는 포트 확인."""
        try:
            port_list = [int(p.strip()) for p in ports.split(",") if p.strip()]
        except ValueError:
            return {"ok": False, "error": "Invalid port list. Use comma-separated integers."}
        results = []
        for port in port_list:
            try:
                sock = socket.create_connection((host, port), timeout=2)
                sock.close()
                results.append({"port": port, "status": "open"})
            except TimeoutError:
                results.append({"port": port, "status": "timeout"})
            except OSError:
                results.append({"port": port, "status": "closed"})
        open_ports = [r for r in results if r["status"] == "open"]
        return {
            "ok": True,
            "host": host,
            "results": results,
            "open_count": len(open_ports),
            "scanned_count": len(results),
        }

    tools.append(
        _attach(
            port_scan,
            _schema(
                "port_scan",
                "TCP port scan to check open ports on a host (firewall verification).",
                {
                    "host": {
                        "type": "string",
                        "description": "Target hostname or IP address.",
                    },
                    "ports": {
                        "type": "string",
                        "description": (
                            "Comma-separated port numbers. "
                            "Default: '22,80,443,3306,5432,6379,8080,8443'."
                        ),
                    },
                },
                ["host"],
            ),
            caps=["security"],
        )
    )

    # -- ssl_check --
    def ssl_check(domain: str, port: int = 443) -> dict:
        """SSL 인증서 상세 정보: 발급자, 만료일, 체인, 프로토콜."""
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, port), timeout=10) as raw:
                with ctx.wrap_socket(raw, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
                    cipher = ssock.cipher()
                    protocol = ssock.version()

            if not cert:
                return {"ok": False, "error": "No certificate returned."}

            # Parse subject and issuer
            def _dn(tuples: tuple) -> dict:
                result: dict[str, str] = {}
                for rdn in tuples:
                    for key, val in rdn:
                        result[key] = val
                return result

            subject = _dn(cert.get("subject", ()))
            issuer = _dn(cert.get("issuer", ()))

            not_before = cert.get("notBefore", "")
            not_after = cert.get("notAfter", "")

            # Calculate days remaining
            days_remaining = None
            status = "valid"
            if not_after:
                expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=timezone.utc
                )
                now = datetime.now(timezone.utc)
                days_remaining = (expiry - now).days
                if days_remaining <= 0:
                    status = "expired"
                elif days_remaining <= 7:
                    status = "critical"
                elif days_remaining <= 30:
                    status = "warning"

            san = cert.get("subjectAltName", ())
            alt_names = [v for _k, v in san]

            return {
                "ok": True,
                "domain": domain,
                "subject": subject,
                "issuer": issuer,
                "serial_number": cert.get("serialNumber", ""),
                "not_before": not_before,
                "not_after": not_after,
                "days_remaining": days_remaining,
                "status": status,
                "protocol": protocol,
                "cipher": cipher[0] if cipher else None,
                "alt_names": alt_names,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            ssl_check,
            _schema(
                "ssl_check",
                "SSL/TLS certificate details: issuer, expiry, chain, protocol version.",
                {
                    "domain": {
                        "type": "string",
                        "description": "Domain name to check.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "TLS port (default: 443).",
                    },
                },
                ["domain"],
            ),
            caps=["security"],
        )
    )

    # -- auth_log_analysis --
    def auth_log_analysis(server: str = "", hours: int = 24) -> dict:
        """SSH 인증 실패 로그 분석 (로컬 또는 SSH 원격)."""
        if _is_darwin():
            cmd = (
                f'log show --predicate \'process == "sshd"\' '
                f"--last {hours}h 2>/dev/null | grep -i failed"
            )
        else:
            cmd = (
                f'journalctl -u sshd -p warning --since "{hours}h ago" '
                f"--no-pager 2>/dev/null | grep -i failed"
            )

        try:
            if server:
                if not secrets:
                    return {"ok": False, "error": "No secrets configured for SSH."}
                result = _ssh_run(secrets, server, cmd, timeout=30)
                if not result.get("ok"):
                    return result
                output = result.get("stdout", "")
            else:
                output = _run(["bash", "-c", cmd], timeout=30)

            lines = [ln for ln in output.splitlines() if ln.strip()]

            # Extract IPs from failed login lines
            ip_pattern = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
            ips: list[str] = []
            for line in lines:
                match = ip_pattern.search(line)
                if match:
                    ips.append(match.group(1))

            ip_counts = Counter(ips).most_common(10)
            top_offenders = [
                {"ip": ip, "attempts": count} for ip, count in ip_counts
            ]

            return {
                "ok": True,
                "server": server or "localhost",
                "hours": hours,
                "total_failures": len(lines),
                "unique_ips": len(set(ips)),
                "top_offenders": top_offenders,
                "sample_lines": lines[:5],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            auth_log_analysis,
            _schema(
                "auth_log_analysis",
                "Analyze failed SSH login attempts from auth logs (local or remote).",
                {
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote analysis (empty = localhost).",
                    },
                    "hours": {
                        "type": "integer",
                        "description": "Hours to look back (default: 24).",
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    # -- vulnerability_check --
    def vulnerability_check(server: str = "") -> dict:
        """미적용 보안 업데이트 확인."""
        if _is_darwin():
            cmd = "softwareupdate -l 2>&1"
        else:
            # Detect package manager
            cmd = (
                "if command -v apt >/dev/null 2>&1; then "
                "  apt list --upgradable 2>/dev/null | grep -i security; "
                "elif command -v yum >/dev/null 2>&1; then "
                "  yum check-update --security 2>/dev/null; "
                "elif command -v dnf >/dev/null 2>&1; then "
                "  dnf check-update --security 2>/dev/null; "
                "else "
                "  echo 'No supported package manager found'; "
                "fi"
            )

        try:
            if server:
                if not secrets:
                    return {"ok": False, "error": "No secrets configured for SSH."}
                result = _ssh_run(secrets, server, cmd, timeout=60)
                if not result.get("ok"):
                    return result
                output = result.get("stdout", "")
            else:
                output = _run(["bash", "-c", cmd], timeout=60)

            lines = [ln for ln in output.splitlines() if ln.strip()]
            updates = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith("Listing") and not line.startswith("WARNING"):
                    updates.append(line)

            return {
                "ok": True,
                "server": server or "localhost",
                "pending_updates": len(updates),
                "updates": updates[:50],
                "platform": "macOS" if _is_darwin() and not server else "Linux",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            vulnerability_check,
            _schema(
                "vulnerability_check",
                "Check for pending security updates (apt/yum/dnf/softwareupdate).",
                {
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote check (empty = localhost).",
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    # -- file_integrity --
    def file_integrity(
        server: str = "",
        paths: str = "/etc/passwd,/etc/shadow,/etc/ssh/sshd_config",
    ) -> dict:
        """파일 해시(SHA-256) 계산으로 무결성 검증."""
        file_list = [p.strip() for p in paths.split(",") if p.strip()]
        if not file_list:
            return {"ok": False, "error": "No file paths provided."}

        try:
            if server:
                if not secrets:
                    return {"ok": False, "error": "No secrets configured for SSH."}
                # Use sha256sum (Linux) or shasum (macOS) on remote
                cmd = (
                    "for f in " + " ".join(file_list) + "; do "
                    "  if [ -f \"$f\" ]; then "
                    "    if command -v sha256sum >/dev/null 2>&1; then "
                    "      sha256sum \"$f\"; "
                    "    else "
                    "      shasum -a 256 \"$f\"; "
                    "    fi; "
                    "  else "
                    "    echo \"MISSING  $f\"; "
                    "  fi; "
                    "done"
                )
                result = _ssh_run(secrets, server, cmd, timeout=30)
                if not result.get("ok"):
                    return result
                output = result.get("stdout", "")
                files = []
                for line in output.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("MISSING"):
                        fpath = line.split(maxsplit=1)[1] if " " in line else line
                        files.append({"path": fpath, "status": "missing", "sha256": None})
                    else:
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            files.append({
                                "path": parts[1].strip(),
                                "status": "ok",
                                "sha256": parts[0],
                            })
            else:
                files = []
                for fpath in file_list:
                    if not os.path.isfile(fpath):
                        files.append({"path": fpath, "status": "missing", "sha256": None})
                        continue
                    try:
                        h = hashlib.sha256()
                        with open(fpath, "rb") as f:
                            for chunk in iter(lambda: f.read(8192), b""):
                                h.update(chunk)
                        files.append({"path": fpath, "status": "ok", "sha256": h.hexdigest()})
                    except PermissionError:
                        files.append({
                            "path": fpath,
                            "status": "permission_denied",
                            "sha256": None,
                        })

            return {
                "ok": True,
                "server": server or "localhost",
                "files": files,
                "checked_count": len(files),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            file_integrity,
            _schema(
                "file_integrity",
                "Compute SHA-256 hashes of critical files for integrity verification.",
                {
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote check (empty = localhost).",
                    },
                    "paths": {
                        "type": "string",
                        "description": (
                            "Comma-separated file paths. "
                            "Default: '/etc/passwd,/etc/shadow,/etc/ssh/sshd_config'."
                        ),
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    # -- container_scan --
    def container_scan(image: str = "", server: str = "") -> dict:
        """컨테이너 이미지 취약점 스캔 (Trivy CLI 연동)."""
        import json as _json

        cmd = f"trivy image --format json --severity HIGH,CRITICAL {image} 2>/dev/null"

        if server:
            if not secrets:
                return {"ok": False, "error": "No secrets configured for SSH."}
            result = _ssh_run(secrets, server, cmd, timeout=120)
            if not result.get("ok"):
                return result
            stdout = result.get("stdout", "")
        else:
            try:
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=120,
                )
                stdout = proc.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return {"ok": False, "error": "trivy not installed or timeout"}

        vulnerabilities: list[dict] = []
        try:
            data = _json.loads(stdout)
            results_list = data.get("Results", []) if isinstance(data, dict) else data
            for r in results_list:
                for v in r.get("Vulnerabilities", []):
                    vulnerabilities.append({
                        "id": v.get("VulnerabilityID", ""),
                        "severity": v.get("Severity", ""),
                        "package": v.get("PkgName", ""),
                        "installed": v.get("InstalledVersion", ""),
                        "fixed": v.get("FixedVersion", ""),
                        "title": v.get("Title", ""),
                    })
        except Exception:
            if not stdout.strip():
                return {
                    "ok": True,
                    "image": image,
                    "vulnerabilities": [],
                    "message": "trivy를 찾을 수 없거나 결과 없음",
                }

        return {
            "ok": True,
            "image": image,
            "total": len(vulnerabilities),
            "critical": len([v for v in vulnerabilities if v["severity"] == "CRITICAL"]),
            "high": len([v for v in vulnerabilities if v["severity"] == "HIGH"]),
            "vulnerabilities": vulnerabilities[:50],
        }

    tools.append(
        _attach(
            container_scan,
            _schema(
                "container_scan",
                "Scan a container image for HIGH/CRITICAL vulnerabilities using Trivy.",
                {
                    "image": {
                        "type": "string",
                        "description": "Docker image name (e.g. 'nginx:latest').",
                    },
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote scan (empty = localhost).",
                    },
                },
                ["image"],
            ),
            caps=["security"],
        )
    )

    # -- dependency_audit --
    def dependency_audit(project_path: str = ".", audit_type: str = "auto") -> dict:
        """의존성 취약점 검사 (npm audit / pip-audit)."""
        import json as _json

        audit_results: list[dict] = []

        # 자동 감지
        types_to_check: list[str] = []
        if audit_type == "auto":
            if os.path.exists(os.path.join(project_path, "package-lock.json")) or os.path.exists(
                os.path.join(project_path, "package.json")
            ):
                types_to_check.append("npm")
            if os.path.exists(os.path.join(project_path, "requirements.txt")) or os.path.exists(
                os.path.join(project_path, "pyproject.toml")
            ):
                types_to_check.append("pip")
        else:
            types_to_check = [audit_type]

        for t in types_to_check:
            if t == "npm":
                try:
                    proc = subprocess.run(
                        ["npm", "audit", "--json"],
                        capture_output=True, text=True, timeout=60, cwd=project_path,
                    )
                    data = _json.loads(proc.stdout) if proc.stdout else {}
                    vulns = data.get("vulnerabilities", {})
                    audit_results.append({
                        "type": "npm",
                        "total": len(vulns),
                        "critical": sum(1 for v in vulns.values() if v.get("severity") == "critical"),
                        "high": sum(1 for v in vulns.values() if v.get("severity") == "high"),
                        "packages": [
                            {"name": k, "severity": v.get("severity", ""), "via": str(v.get("via", ""))[:100]}
                            for k, v in list(vulns.items())[:30]
                        ],
                    })
                except Exception as e:
                    audit_results.append({"type": "npm", "error": str(e)})

            elif t == "pip":
                try:
                    proc = subprocess.run(
                        ["pip-audit", "--format", "json", "-r", os.path.join(project_path, "requirements.txt")],
                        capture_output=True, text=True, timeout=60,
                    )
                    data = _json.loads(proc.stdout) if proc.stdout else []
                    audit_results.append({
                        "type": "pip",
                        "total": len(data),
                        "packages": [
                            {"name": v.get("name", ""), "version": v.get("version", ""), "fix": v.get("fix_versions", []), "id": v.get("id", "")}
                            for v in data[:30]
                        ],
                    })
                except Exception as e:
                    audit_results.append({"type": "pip", "error": str(e)})

        return {"ok": True, "audits": audit_results}

    tools.append(
        _attach(
            dependency_audit,
            _schema(
                "dependency_audit",
                "Audit project dependencies for known vulnerabilities (npm audit / pip-audit).",
                {
                    "project_path": {
                        "type": "string",
                        "description": "Project directory path (default: '.').",
                    },
                    "audit_type": {
                        "type": "string",
                        "description": "Audit type: 'npm', 'pip', or 'auto' (auto-detect). Default: 'auto'.",
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    # -- firewall_check --
    def firewall_check(server: str = "") -> dict:
        """방화벽 규칙 검증 (iptables/ufw/nftables)."""
        commands = {
            "ufw": "sudo ufw status verbose 2>/dev/null",
            "iptables": "sudo iptables -L -n --line-numbers 2>/dev/null",
            "nftables": "sudo nft list ruleset 2>/dev/null | head -50",
        }

        rules: list[dict] = []

        for fw_type, cmd in commands.items():
            if server:
                if not secrets:
                    continue
                result = _ssh_run(secrets, server, cmd, timeout=15)
                stdout = result.get("stdout", "") if result.get("ok") else ""
            else:
                try:
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True, timeout=15,
                    )
                    stdout = proc.stdout
                except Exception:
                    continue

            if stdout.strip():
                rules.append({"type": fw_type, "output": stdout.strip()[:2000]})

        return {
            "ok": True,
            "server": server or "localhost",
            "rules": rules,
        }

    tools.append(
        _attach(
            firewall_check,
            _schema(
                "firewall_check",
                "Check firewall rules (iptables/ufw/nftables) on local or remote server.",
                {
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote check (empty = localhost).",
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    # -- security_score --
    def security_score(server: str = "") -> dict:
        """종합 보안 점수 산출 — 항목별 점수를 계산하여 종합 등급을 반환."""
        scores: dict[str, dict] = {}
        total = 0

        # 1. SSL 인증서 (25점)
        ssl_result = ssl_check(domain="localhost", port=443)
        if ssl_result.get("ok"):
            status = ssl_result.get("status", "")
            if status == "valid":
                scores["ssl"] = {"score": 25, "max": 25, "status": "양호"}
            elif status == "warning":
                scores["ssl"] = {"score": 15, "max": 25, "status": "주의"}
            else:
                scores["ssl"] = {"score": 0, "max": 25, "status": "위험"}
        else:
            scores["ssl"] = {"score": 15, "max": 25, "status": "확인 불가"}
        total += scores["ssl"]["score"]

        # 2. 포트 노출 (25점)
        port_result = port_scan(host="127.0.0.1", ports="22,80,443,3306,5432,6379,27017")
        if port_result.get("ok"):
            open_risky = sum(
                1
                for p in port_result.get("results", [])
                if p.get("status") == "open" and p.get("port") in [3306, 5432, 6379, 27017]
            )
            if open_risky == 0:
                scores["ports"] = {"score": 25, "max": 25, "status": "양호"}
            elif open_risky <= 1:
                scores["ports"] = {"score": 15, "max": 25, "status": "주의"}
            else:
                scores["ports"] = {"score": 5, "max": 25, "status": "위험"}
        else:
            scores["ports"] = {"score": 15, "max": 25, "status": "확인 불가"}
        total += scores["ports"]["score"]

        # 3. 방화벽 (25점)
        fw = firewall_check(server=server)
        if fw.get("rules"):
            scores["firewall"] = {"score": 25, "max": 25, "status": "활성"}
        else:
            scores["firewall"] = {"score": 5, "max": 25, "status": "미확인"}
        total += scores["firewall"]["score"]

        # 4. 인증 로그 (25점)
        if server:
            auth = auth_log_analysis(server=server, hours=24)
        else:
            auth = auth_log_analysis(hours=24)
        if auth.get("ok"):
            suspicious = auth.get("unique_ips", 0)
            if suspicious == 0:
                scores["auth"] = {"score": 25, "max": 25, "status": "양호"}
            elif suspicious <= 3:
                scores["auth"] = {"score": 15, "max": 25, "status": "주의"}
            else:
                scores["auth"] = {"score": 5, "max": 25, "status": "위험"}
        else:
            scores["auth"] = {"score": 15, "max": 25, "status": "확인 불가"}
        total += scores["auth"]["score"]

        overall = round(total / 100 * 100)
        grade = "A" if overall >= 90 else "B" if overall >= 70 else "C" if overall >= 50 else "D"

        return {
            "ok": True,
            "server": server or "localhost",
            "overall_score": overall,
            "grade": grade,
            "categories": scores,
        }

    tools.append(
        _attach(
            security_score,
            _schema(
                "security_score",
                "Calculate an overall security score (SSL, ports, firewall, auth logs).",
                {
                    "server": {
                        "type": "string",
                        "description": "Server ID for remote assessment (empty = localhost).",
                    },
                },
                [],
            ),
            caps=["security"],
        )
    )

    return tools
