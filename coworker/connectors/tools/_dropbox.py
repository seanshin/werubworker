"""Dropbox connector tools."""

from __future__ import annotations

import json
from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _clamp, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    def _dropbox_path(path: str) -> str:
        path = (path or "").strip()
        if path and not path.startswith("/"):
            path = "/" + path
        return path

    def dropbox_search(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "dropbox", "access_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            "https://api.dropboxapi.com/2/files/search_v2",
            headers=_bearer_headers(profile["access_token"]),
            json={"query": query, "options": {"max_results": _clamp(max_results)}},
        )

    dropbox_search.__name__ = "dropbox_search"
    tools.append(
        _attach(
            dropbox_search,
            _schema(
                "dropbox_search",
                "Search Dropbox files and folders by name/content.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["dropbox", "read"],
        )
    )

    def dropbox_list_folder(path: str = "") -> dict[str, Any]:
        profile, err = _profile(secrets, "dropbox", "access_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            "https://api.dropboxapi.com/2/files/list_folder",
            headers=_bearer_headers(profile["access_token"]),
            json={"path": _dropbox_path(path)},
        )

    dropbox_list_folder.__name__ = "dropbox_list_folder"
    tools.append(
        _attach(
            dropbox_list_folder,
            _schema(
                "dropbox_list_folder",
                "List a Dropbox folder. Empty path is the root.",
                {"path": {"type": "string"}},
                [],
            ),
            caps=["dropbox", "read"],
        )
    )

    def dropbox_read_file(path: str, max_chars: int = 20000) -> dict[str, Any]:
        profile, err = _profile(secrets, "dropbox", "access_token")
        if err:
            return err
        out = _helpers._request(
            "POST",
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {profile['access_token']}",
                "Dropbox-API-Arg": json.dumps({"path": _dropbox_path(path)}),
            },
        )
        if "error" in out:
            return out
        text = out["data"] if isinstance(out["data"], str) else str(out["data"])
        cap = max(1, min(int(max_chars or 20000), 100000))
        return {"path": path, "text": text[:cap], "truncated": len(text) > cap}

    dropbox_read_file.__name__ = "dropbox_read_file"
    tools.append(
        _attach(
            dropbox_read_file,
            _schema(
                "dropbox_read_file",
                "Read a text file from Dropbox by path.",
                {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
                ["path"],
            ),
            caps=["dropbox", "read"],
        )
    )
