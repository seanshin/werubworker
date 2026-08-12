"""Filter credentials from agent responses before sending to the user.

This module provides a post-processing step that detects and masks
credential values that may have leaked into agent text output.
"""

from __future__ import annotations

import re
from typing import Sequence

# Well-known credential patterns
_CREDENTIAL_PATTERNS = [
    (re.compile(r'\b(sk-[a-zA-Z0-9]{20,})\b'), "OpenAI API Key"),
    (re.compile(r'\b(AKIA[A-Z0-9]{16})\b'), "AWS Access Key"),
    (re.compile(r'\b(ghp_[a-zA-Z0-9]{36})\b'), "GitHub PAT"),
    (re.compile(r'\b(ghs_[a-zA-Z0-9]{36})\b'), "GitHub App Token"),
    (re.compile(r'\b(xoxb-[a-zA-Z0-9\-]+)\b'), "Slack Bot Token"),
    (re.compile(r'\b(xoxp-[a-zA-Z0-9\-]+)\b'), "Slack User Token"),
    (re.compile(r'\b(glpat-[a-zA-Z0-9_\-]{20,})\b'), "GitLab PAT"),
    (re.compile(r'\b(npm_[a-zA-Z0-9]{36})\b'), "npm Token"),
]


def mask_value(value: str) -> str:
    """Mask a credential value, preserving first/last 4 chars."""
    if len(value) <= 8:
        return "••••••••"
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


def filter_credentials(
    text: str,
    known_secrets: Sequence[str] = (),
) -> str:
    """Remove credential values from text.

    1. First checks for any *known_secrets* (exact values retrieved from vault)
    2. Then scans for well-known credential patterns (API keys, tokens, etc.)

    Returns the filtered text with credentials replaced by masked versions.
    """
    # Phase 1: exact match against known vault values
    for secret in known_secrets:
        if len(secret) >= 8 and secret in text:
            text = text.replace(secret, mask_value(secret))

    # Phase 2: pattern-based detection
    for pattern, label in _CREDENTIAL_PATTERNS:
        text = pattern.sub(lambda m: f"[{label} REDACTED]", text)

    return text
