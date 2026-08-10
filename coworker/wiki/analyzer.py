"""Wiki document AI analyzer — extracts service credentials and connection info
from free-form markdown documents.

Users write wiki pages naturally (Korean or English). The analyzer scans the
content for patterns matching hostnames, ports, passwords, API keys, tokens,
and other service configuration data. Extracted items are presented for user
confirmation before being stored in the vault and synced to secrets.json.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Pattern definitions for credential/service info extraction
# ---------------------------------------------------------------------------

_PATTERNS: list[dict[str, Any]] = [
    # IP addresses
    {
        "name": "host",
        "label": "호스트/IP",
        "pattern": r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
        "secret": False,
    },
    # Hostnames (xxx.xxx.xxx format)
    {
        "name": "hostname",
        "label": "호스트명",
        "pattern": r"\b([a-zA-Z0-9][-a-zA-Z0-9]*\.[-a-zA-Z0-9.]+[a-zA-Z])\b",
        "secret": False,
    },
    # Ports (after "포트" or "port" or ":" followed by number)
    {
        "name": "port",
        "label": "포트",
        "pattern": r"(?:포트|port|Port)[:\s]*(\d{2,5})\b",
        "secret": False,
    },
    # URLs
    {"name": "url", "label": "URL", "pattern": r"(https?://[^\s\)\"\'`]+)", "secret": False},
    # SSH user@host
    {
        "name": "ssh_target",
        "label": "SSH 접속",
        "pattern": r"\b([a-zA-Z0-9_]+)@(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[a-zA-Z0-9][-a-zA-Z0-9.]+)\b",
        "secret": False,
    },
    # API Keys / Tokens
    {"name": "api_key", "label": "API 키", "pattern": r"\b(sk-[a-zA-Z0-9]{20,})\b", "secret": True},
    {
        "name": "api_key_generic",
        "label": "API 키",
        "pattern": r'(?:api[_\s-]?key|API[_\s-]?KEY|token|Token|TOKEN)[:\s=]+["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        "secret": True,
    },
    # AWS Keys
    {
        "name": "aws_access_key",
        "label": "AWS Access Key",
        "pattern": r"\b(AKIA[A-Z0-9]{16})\b",
        "secret": True,
    },
    {
        "name": "aws_secret_key",
        "label": "AWS Secret Key",
        "pattern": r'(?:secret[_\s]?(?:access[_\s]?)?key|SECRET_KEY)[:\s=]+["\']?([a-zA-Z0-9/+=]{30,})["\']?',
        "secret": True,
    },
    # Slack tokens
    {
        "name": "slack_token",
        "label": "Slack 토큰",
        "pattern": r"\b(xoxb-[a-zA-Z0-9\-]+)\b",
        "secret": True,
    },
    {
        "name": "slack_app_token",
        "label": "Slack App 토큰",
        "pattern": r"\b(xapp-[a-zA-Z0-9\-]+)\b",
        "secret": True,
    },
    # GitHub PAT
    {
        "name": "github_pat",
        "label": "GitHub PAT",
        "pattern": r"\b(ghp_[a-zA-Z0-9]{36})\b",
        "secret": True,
    },
    # Generic passwords (after "비밀번호" or "password" or "PW")
    {
        "name": "password",
        "label": "비밀번호",
        "pattern": r'(?:비밀번호|password|Password|PW|pw|passwd)[:\s=]+["\']?([^\s"\'`\n]{4,})["\']?',
        "secret": True,
    },
    # Database connection strings
    {
        "name": "db_url",
        "label": "DB 연결 문자열",
        "pattern": r'((?:postgres|mysql|mongodb|redis)(?:ql)?://[^\s"\'`]+)',
        "secret": True,
    },
    # Bearer tokens
    {
        "name": "bearer",
        "label": "Bearer 토큰",
        "pattern": r"(?:Bearer|bearer)\s+([a-zA-Z0-9_\-\.]{20,})",
        "secret": True,
    },
]

# Context patterns: lines that indicate what a credential belongs to
_CONTEXT_PATTERNS: list[dict[str, str]] = [
    {"pattern": r"(?:서버|server|Server|호스트|host|Host)", "category": "server"},
    {
        "pattern": r"(?:데이터베이스|database|Database|DB|db|MySQL|PostgreSQL|Redis|MongoDB)",
        "category": "database",
    },
    {"pattern": r"(?:AWS|aws|S3|EC2|CloudWatch|Lambda)", "category": "cloud"},
    {"pattern": r"(?:Cloudflare|cloudflare|CF|DNS)", "category": "cloud"},
    {"pattern": r"(?:Wasabi|wasabi|S3\s*호환)", "category": "cloud"},
    {"pattern": r"(?:Slack|slack|GitHub|github|Jira|jira|Notion|notion)", "category": "saas"},
    {"pattern": r"(?:SSH|ssh)", "category": "server"},
    {"pattern": r"(?:Docker|docker|컨테이너|container)", "category": "server"},
    {"pattern": r"(?:API|api|토큰|token|키|key)", "category": "api"},
    {"pattern": r"(?:SSL|ssl|인증서|certificate|cert)", "category": "security"},
    {"pattern": r"(?:Ollama|ollama|모델|model|AI|ai)", "category": "ai"},
]

# Service type detection: determines linked_service prefix
_SERVICE_DETECTION: list[dict[str, str]] = [
    {"pattern": r"(?:PostgreSQL|postgresql|postgres|psql)", "service_prefix": "database"},
    {"pattern": r"(?:MySQL|mysql|mariadb)", "service_prefix": "database"},
    {"pattern": r"(?:Redis|redis)", "service_prefix": "database"},
    {"pattern": r"(?:MongoDB|mongodb|mongo)", "service_prefix": "database"},
    {"pattern": r"(?:SSH|ssh)", "service_prefix": "ssh:server"},
    {"pattern": r"(?:AWS|aws)", "service_prefix": "aws"},
    {"pattern": r"(?:Cloudflare|cloudflare)", "service_prefix": "cloudflare"},
    {"pattern": r"(?:Wasabi|wasabi)", "service_prefix": "wasabi"},
    {"pattern": r"(?:Slack|slack)", "service_prefix": "slack"},
    {"pattern": r"(?:GitHub|github)", "service_prefix": "github"},
    {"pattern": r"(?:Ollama|ollama)", "service_prefix": "provider:openai"},
]


def analyze_document(content: str, title: str = "") -> dict[str, Any]:
    """Analyze a free-form wiki document and extract credentials/service info.

    Returns:
        {
            "credentials": [
                {"key": "db_host", "label": "호스트", "value": "192.168.1.20",
                 "secret": false, "context": "프로덕션 DB 서버", "line": 5},
                ...
            ],
            "suggested_category": "database",
            "suggested_service": "database:production",
            "suggested_name": "Production DB",
            "summary": "PostgreSQL 데이터베이스 접속 정보 (1개 호스트, 1개 비밀번호 감지)"
        }
    """
    lines = content.split("\n")
    found: list[dict[str, Any]] = []
    seen_values: set[str] = set()

    for i, line in enumerate(lines, 1):
        for pat in _PATTERNS:
            for match in re.finditer(pat["pattern"], line):
                value = (
                    match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                )
                # Skip duplicates and very short matches
                if value in seen_values or len(value) < 3:
                    continue
                # Skip common false positives
                if _is_false_positive(value, pat["name"]):
                    continue
                seen_values.add(value)
                context = _get_context(lines, i - 1)
                found.append(
                    {
                        "key": _generate_key(pat["name"], len(found)),
                        "label": pat["label"],
                        "value": value,
                        "secret": pat["secret"],
                        "pattern_name": pat["name"],
                        "context": context,
                        "line": i,
                    }
                )

    category = _detect_category(content, title)
    service = _detect_service(content, title)
    name = title or _extract_title(content)

    secret_count = sum(1 for f in found if f["secret"])
    non_secret_count = len(found) - secret_count
    summary_parts = []
    if non_secret_count:
        summary_parts.append(f"{non_secret_count}개 연결 정보")
    if secret_count:
        summary_parts.append(f"{secret_count}개 자격증명")
    summary = f"{', '.join(summary_parts)} 감지" if summary_parts else "추출 가능한 정보 없음"

    return {
        "credentials": found,
        "suggested_category": category,
        "suggested_service": service,
        "suggested_name": name,
        "summary": summary,
    }


def _is_false_positive(value: str, pattern_name: str) -> bool:
    """Filter out common false positives."""
    # Skip common domains first
    skip_domains = {"example.com", "localhost", "127.0.0.1", "0.0.0.0"}
    if value.lower() in skip_domains:
        return True
    # Skip version numbers like 1.2.3.4
    if pattern_name == "host":
        parts = value.split(".")
        if all(p.isdigit() and int(p) < 10 for p in parts):
            return True
    # Skip markdown syntax
    if value.startswith("#") or value.startswith("```"):
        return True
    return False


def _get_context(lines: list[str], line_idx: int, window: int = 2) -> str:
    """Get surrounding context for a found credential."""
    start = max(0, line_idx - window)
    end = min(len(lines), line_idx + window + 1)
    context_lines = []
    for i in range(start, end):
        line = lines[i].strip()
        if line and not line.startswith("```") and not line.startswith("---"):
            # Find headers or labels near this line
            if line.startswith("#") or ":" in line or "|" in line:
                context_lines.append(line.lstrip("#").strip())
    return " > ".join(context_lines[:3]) if context_lines else ""


def _detect_category(content: str, title: str = "") -> str:
    """Detect the most likely category from content."""
    text = f"{title} {content}".lower()
    scores: dict[str, int] = {}
    for cp in _CONTEXT_PATTERNS:
        matches = len(re.findall(cp["pattern"], text, re.IGNORECASE))
        if matches:
            scores[cp["category"]] = scores.get(cp["category"], 0) + matches
    if scores:
        return max(scores, key=scores.get)
    return "general"


def _detect_service(content: str, title: str = "") -> str:
    """Detect a linked_service value from content."""
    text = f"{title} {content}"
    for sd in _SERVICE_DETECTION:
        if re.search(sd["pattern"], text, re.IGNORECASE):
            # Try to find a name/identifier
            name = _extract_service_name(text, sd["service_prefix"])
            return f"{sd['service_prefix']}:{name}" if name else sd["service_prefix"]
    return ""


def _extract_service_name(text: str, prefix: str) -> str:
    """Try to extract a service instance name (production, staging, etc.)."""
    for name_pat in [
        r"(production|staging|development|dev|prod|test)",
        r"(main|primary|secondary|replica)",
        r"(web|api|app|worker|db)[-_]?(\d+)?",
    ]:
        match = re.search(name_pat, text, re.IGNORECASE)
        if match:
            return match.group(0).lower().replace(" ", "-")
    return "default"


def _extract_title(content: str) -> str:
    """Extract a title from the first heading or first non-empty line."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if line and not line.startswith("---") and not line.startswith("```"):
            return line[:50]
    return "Untitled"


def _generate_key(pattern_name: str, index: int) -> str:
    """Generate a unique credential key."""
    base = pattern_name.replace("_generic", "")
    return f"{base}_{index}" if index > 0 else base
