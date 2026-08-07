"""Per-connector tool modules, assembled by make_integration_tools().

Each sub-module exposes a ``register(secrets, tools, *, roots=None)`` function
that appends its tool closures to *tools*.
"""

from __future__ import annotations

# Re-export from the original connectors/tools.py (now _send_tools.py) so
# existing `from .tools import make_send_message_tool` continues to work.
from .._send_tools import make_send_file_tool, make_send_message_tool  # noqa: F401

from typing import Any, Callable, Optional

from ...secrets import SecretStore
from ..browser_automation import make_browser_automation_tools
from ..email_tools import make_email_tools
from ..tool_defs import connector_for_tool
from . import (
    _analytics,
    _apollo_hunter,
    _asana,
    _attio,
    _box,
    _browser,
    _canva,
    _clickup,
    _close,
    _discord,
    _docusign,
    _dropbox,
    _figma,
    _gcal,
    _gdrive,
    _github,
    _gitlab,
    _gmail,
    _hubspot,
    _jira,
    _linear,
    _notion,
    _outlook,
    _quickbooks,
    _stripe,
    _whatsapp,
    _zendesk,
)

_CONNECTOR_MODULES = [
    _browser,
    _github,
    _gmail,
    _gcal,
    _outlook,
    _jira,
    _zendesk,
    _linear,
    _gitlab,
    _discord,
    _stripe,
    _asana,
    _hubspot,
    _dropbox,
    _box,
    _quickbooks,
    _whatsapp,
    _notion,
    _attio,
    _analytics,
    _apollo_hunter,
    _clickup,
    _close,
    _figma,
    _gdrive,
    _docusign,
    _canva,
]


def make_integration_tools(
    secrets: SecretStore,
    *,
    enabled_connectors: Optional[set[str]] = None,
    enabled_tools: Optional[set[str]] = None,
    roots: Optional[list[Any]] = None,
) -> list[Callable[..., Any]]:
    tools: list[Callable[..., Any]] = make_browser_automation_tools()
    # Email needs the session roots: attachment downloads land in the primary scratch
    # and outgoing attachments must resolve inside a granted directory.
    tools.extend(make_email_tools(secrets, roots=roots))

    for mod in _CONNECTOR_MODULES:
        mod.register(secrets, tools, roots=roots)

    if enabled_connectors is not None:
        tools = [
            t for t in tools if connector_for_tool(t.__name__) in enabled_connectors
        ]
    if enabled_tools is not None:
        tools = [t for t in tools if t.__name__ in enabled_tools]
    return tools
