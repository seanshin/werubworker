"""Audit-log-specific sensitive data filter.

Detects and masks credentials, PII, and secrets in audit log entries
and operational commands. Separate from response_filter.py which
handles agent response output masking with different replacement styles.

Performance: uses a combined pre-check pattern to skip texts that
contain no sensitive data (common case) without running all 14 patterns.
"""

from __future__ import annotations

import re

# --- General patterns (API keys, tokens, PII) ---

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API keys / tokens
    (re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b"), "[ANTHROPIC_KEY]"),
    (re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"), "[API_KEY]"),
    (re.compile(r"\b(AKIA[A-Z0-9]{16})\b"), "[AWS_KEY]"),
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b"), "[GITHUB_PAT]"),
    (re.compile(r"\b(ghs_[a-zA-Z0-9]{36})\b"), "[GITHUB_APP]"),
    (re.compile(r"\b(xox[bprs]-[a-zA-Z0-9\-]+)\b"), "[SLACK_TOKEN]"),
    (re.compile(r"\b(glpat-[a-zA-Z0-9_\-]{20,})\b"), "[GITLAB_PAT]"),
    (re.compile(r"\b(npm_[a-zA-Z0-9]{36})\b"), "[NPM_TOKEN]"),
    # Bearer token
    (re.compile(r"(?i)Bearer\s+[a-zA-Z0-9_\-\.]{20,}"), "Bearer [REDACTED]"),
    # Password assignment
    (re.compile(r"(?i)(?:password|passwd|pwd)\s*[=:]\s*\S+"), "password=[REDACTED]"),
    (re.compile(r"(?i)--password[= ]\S+"), "--password [REDACTED]"),
    # Korean PII
    (re.compile(r"\b\d{6}-?[1-4]\d{6}\b"), "[주민번호]"),
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[전화번호]"),
    # DB connection URI
    (re.compile(
        r"(?i)(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis|amqp)://"
        r"[^@\s]+@[^\s]+"
    ), "[DB_URI]"),
]

# Pre-check: combined pattern for fast rejection (single regex scan)
_QUICK_CHECK = re.compile(
    r"(?i)"
    r"sk-|AKIA|ghp_|ghs_|xox[bprs]-|glpat-|npm_|"
    r"Bearer\s|password|passwd|pwd|--password|"
    r"\d{6}-?[1-4]\d{6}|01[016789]-?\d{3,4}-?\d{4}|"
    r"(?:mysql|postgres|mongodb|redis|amqp)://"
)

# --- Command-specific patterns (SSH, DB CLI) ---

_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)sshpass\s+-p\s+\S+"), "sshpass -p [REDACTED]"),
    (re.compile(r"(?i)PGPASSWORD=\S+"), "PGPASSWORD=[REDACTED]"),
    (re.compile(r"(?i)MYSQL_PWD=\S+"), "MYSQL_PWD=[REDACTED]"),
    (re.compile(r"(?i)mysql\s+.*?-p\S+"),
     lambda m: re.sub(r"-p\S+", "-p[REDACTED]", m.group())),
    (re.compile(
        r"(?i)export\s+\w*(?:PASSWORD|SECRET|TOKEN|KEY)\w*=\S+"
    ), lambda m: re.sub(r"=\S+", "=[REDACTED]", m.group())),
]

_CMD_QUICK_CHECK = re.compile(
    r"(?i)sshpass|PGPASSWORD|MYSQL_PWD|mysql\s.*-p|export\s+\w*(?:PASSWORD|SECRET|TOKEN|KEY)"
)


def sanitize_text(text: str) -> str:
    """Mask sensitive data in arbitrary text."""
    if not text or len(text) < 4:
        return text
    if not _QUICK_CHECK.search(text):
        return text  # fast path: no sensitive patterns found
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_command(command: str) -> str:
    """Mask sensitive data in SSH/DB commands.

    Applies command-specific patterns first, then general patterns.
    """
    if not command:
        return command
    if _CMD_QUICK_CHECK.search(command):
        for pattern, replacement in _COMMAND_PATTERNS:
            if callable(replacement):
                command = pattern.sub(replacement, command)
            else:
                command = pattern.sub(replacement, command)
    return sanitize_text(command)
