"""Network diagnostic tools — traceroute, MTR, DNS lookup, DNS propagation, bandwidth test.

Read-only network tools for diagnosing connectivity, routing, and DNS issues.
All tools run locally via subprocess or via httpx for bandwidth measurement.
"""

from __future__ import annotations

import platform
import re
import subprocess
import time
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


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


# ---------------------------------------------------------------------------
# Schema helpers (mirrors cloud_infra.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="network_diag",
        risk_level="low",
        capabilities=capabilities or ["network"],
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


def network_diag_tools(context: Any = None) -> list:
    """Return network diagnostic tools."""
    secrets = getattr(context, "secrets", None)
    tools: list[Callable[..., Any]] = []

    # -- net_traceroute --
    def net_traceroute(host: str, max_hops: int = 30) -> dict:
        """traceroute/tracepath로 네트워크 경로 추적."""
        try:
            if _is_darwin():
                cmd = ["traceroute", "-m", str(max_hops), host]
            else:
                # Try traceroute first, fall back to tracepath
                which = _run(["which", "traceroute"])
                if which:
                    cmd = ["traceroute", "-m", str(max_hops), host]
                else:
                    cmd = ["tracepath", "-m", str(max_hops), host]

            output = _run(cmd, timeout=60)
            if not output:
                return {"ok": False, "error": "traceroute command returned no output."}

            hops = []
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Parse hop number at start of line
                match = re.match(r"^\s*(\d+)\s+(.+)$", line)
                if match:
                    hops.append({
                        "hop": int(match.group(1)),
                        "detail": match.group(2).strip(),
                    })

            return {
                "ok": True,
                "host": host,
                "max_hops": max_hops,
                "hops": hops,
                "hop_count": len(hops),
                "raw": output,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            net_traceroute,
            _schema(
                "net_traceroute",
                "Trace network route to a host using traceroute/tracepath.",
                {
                    "host": {
                        "type": "string",
                        "description": "Target hostname or IP address.",
                    },
                    "max_hops": {
                        "type": "integer",
                        "description": "Maximum number of hops (default: 30).",
                    },
                },
                ["host"],
            ),
            caps=["network"],
        )
    )

    # -- mtr_report --
    def mtr_report(host: str, count: int = 10) -> dict:
        """MTR 보고서 — traceroute + ping 통합."""
        try:
            which = _run(["which", "mtr"])
            if not which:
                return {"ok": False, "error": "mtr is not installed on this system."}

            cmd = ["mtr", "--report", "--report-cycles", str(count), host]
            output = _run(cmd, timeout=120)
            if not output:
                return {"ok": False, "error": "mtr command returned no output."}

            hops = []
            for line in output.splitlines():
                line = line.strip()
                if not line or line.startswith("Start") or line.startswith("HOST"):
                    continue
                # Typical MTR line: |-- hop  Loss%   Snt  Last  Avg  Best  Wrst StDev
                match = re.match(
                    r"^\|?[-\s]*\d+[\.\|]\|?[-\s]*(\S+)\s+"
                    r"([\d.]+)%?\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+"
                    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                    line,
                )
                if match:
                    hops.append({
                        "host": match.group(1),
                        "loss_pct": float(match.group(2)),
                        "sent": int(match.group(3)),
                        "last_ms": float(match.group(4)),
                        "avg_ms": float(match.group(5)),
                        "best_ms": float(match.group(6)),
                        "worst_ms": float(match.group(7)),
                        "stdev": float(match.group(8)),
                    })

            return {
                "ok": True,
                "host": host,
                "cycles": count,
                "hops": hops,
                "hop_count": len(hops),
                "raw": output,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            mtr_report,
            _schema(
                "mtr_report",
                "MTR (My TraceRoute) report — combined traceroute + ping statistics.",
                {
                    "host": {
                        "type": "string",
                        "description": "Target hostname or IP address.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of ping cycles (default: 10).",
                    },
                },
                ["host"],
            ),
            caps=["network"],
        )
    )

    # -- dns_lookup --
    def dns_lookup(domain: str, record_type: str = "A") -> dict:
        """DNS 레코드 조회 (A, AAAA, MX, NS, TXT, CNAME, SOA)."""
        record_type = record_type.upper()
        valid_types = {"A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "PTR", "SRV"}
        if record_type not in valid_types:
            return {
                "ok": False,
                "error": f"Unsupported record type '{record_type}'. "
                f"Supported: {', '.join(sorted(valid_types))}.",
            }
        try:
            # Try dig first, fall back to nslookup
            which_dig = _run(["which", "dig"])
            if which_dig:
                output = _run(["dig", "+short", domain, record_type], timeout=10)
            else:
                output = _run(
                    ["nslookup", f"-type={record_type}", domain], timeout=10
                )

            if not output:
                return {
                    "ok": True,
                    "domain": domain,
                    "type": record_type,
                    "records": [],
                    "count": 0,
                }

            records = [ln.strip() for ln in output.splitlines() if ln.strip()]
            return {
                "ok": True,
                "domain": domain,
                "type": record_type,
                "records": records,
                "count": len(records),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            dns_lookup,
            _schema(
                "dns_lookup",
                "DNS record lookup (A, AAAA, MX, NS, TXT, CNAME, SOA, PTR, SRV).",
                {
                    "domain": {
                        "type": "string",
                        "description": "Domain name to query.",
                    },
                    "record_type": {
                        "type": "string",
                        "description": "DNS record type (default: 'A').",
                    },
                },
                ["domain"],
            ),
            caps=["network"],
        )
    )

    # -- dns_propagation --
    def dns_propagation(domain: str, expected: str = "") -> dict:
        """여러 공용 DNS 서버에서 조회하여 전파 상태 확인."""
        public_dns = {
            "Google": "8.8.8.8",
            "Cloudflare": "1.1.1.1",
            "OpenDNS": "208.67.222.222",
            "Quad9": "9.9.9.9",
        }
        results = []
        try:
            for name, server in public_dns.items():
                # Use nslookup with specific server
                output = _run(
                    ["nslookup", domain, server], timeout=10
                )
                # Extract resolved addresses
                addresses: list[str] = []
                in_answer = False
                for line in output.splitlines():
                    line = line.strip()
                    if "Name:" in line:
                        in_answer = True
                    if in_answer and "Address:" in line:
                        addr = line.split("Address:")[-1].strip()
                        if addr and addr != server:
                            addresses.append(addr)
                    elif "Address:" in line and "#53" not in line:
                        addr = line.split("Address:")[-1].strip()
                        if addr and addr != server:
                            addresses.append(addr)

                matches_expected = (
                    expected in addresses if expected else None
                )
                results.append({
                    "dns_server": name,
                    "server_ip": server,
                    "resolved": addresses,
                    "matches_expected": matches_expected,
                })

            # Check consistency
            all_resolved = [tuple(sorted(r["resolved"])) for r in results if r["resolved"]]
            consistent = len(set(all_resolved)) <= 1 if all_resolved else False

            return {
                "ok": True,
                "domain": domain,
                "expected": expected or None,
                "results": results,
                "consistent": consistent,
                "servers_checked": len(results),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            dns_propagation,
            _schema(
                "dns_propagation",
                "Check DNS propagation across multiple public DNS servers.",
                {
                    "domain": {
                        "type": "string",
                        "description": "Domain name to check.",
                    },
                    "expected": {
                        "type": "string",
                        "description": "Expected IP address (optional, for match checking).",
                    },
                },
                ["domain"],
            ),
            caps=["network"],
        )
    )

    # -- bandwidth_test --
    def bandwidth_test(url: str = "http://speedtest.tele2.net/1MB.zip") -> dict:
        """URL 다운로드로 간단한 대역폭 측정."""
        try:
            import httpx

            start = time.time()
            total_bytes = 0
            with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(chunk_size=65536):
                    total_bytes += len(chunk)
            elapsed = time.time() - start

            if elapsed <= 0:
                return {"ok": False, "error": "Download completed too fast to measure."}

            speed_bps = (total_bytes * 8) / elapsed
            speed_mbps = speed_bps / 1_000_000

            return {
                "ok": True,
                "url": url,
                "size_bytes": total_bytes,
                "elapsed_seconds": round(elapsed, 3),
                "speed_mbps": round(speed_mbps, 2),
                "speed_human": f"{speed_mbps:.2f} Mbps",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            bandwidth_test,
            _schema(
                "bandwidth_test",
                "Simple bandwidth test by downloading a file and measuring speed.",
                {
                    "url": {
                        "type": "string",
                        "description": (
                            "URL to download for speed test. "
                            "Default: 'http://speedtest.tele2.net/1MB.zip'."
                        ),
                    },
                },
                [],
            ),
            caps=["network"],
        )
    )

    return tools
