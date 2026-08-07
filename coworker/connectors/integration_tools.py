"""Backward-compat re-export. New code should import from connectors.tools."""

from .tools import make_integration_tools  # noqa: F401

# Compat: tests monkeypatch _request at this path. The canonical target is now
# coworker.connectors.tools._helpers (per-connector modules look it up through
# the _helpers module object at call time, so patching _helpers._request works).
from .tools import _helpers as _helpers  # noqa: F401
from .tools._helpers import _request  # noqa: F401
