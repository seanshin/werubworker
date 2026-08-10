"""Box connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _clamp, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    def box_search(query: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "box", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            "https://api.box.com/2.0/search",
            headers=_bearer_headers(profile["access_token"]),
            params={"query": query, "limit": _clamp(max_results)},
        )

    box_search.__name__ = "box_search"
    tools.append(
        _attach(
            box_search,
            _schema(
                "box_search",
                "Search Box files and folders.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["box", "read"],
        )
    )

    def box_list_folder(folder_id: str = "0") -> dict[str, Any]:
        profile, err = _profile(secrets, "box", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"https://api.box.com/2.0/folders/{folder_id}/items",
            headers=_bearer_headers(profile["access_token"]),
        )

    box_list_folder.__name__ = "box_list_folder"
    tools.append(
        _attach(
            box_list_folder,
            _schema(
                "box_list_folder",
                "List items in a Box folder. Folder '0' is the root.",
                {"folder_id": {"type": "string"}},
                [],
            ),
            caps=["box", "read"],
        )
    )

    def box_read_file(file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        profile, err = _profile(secrets, "box", "access_token")
        if err:
            return err
        out = _helpers._request(
            "GET",
            f"https://api.box.com/2.0/files/{file_id}/content",
            headers=_bearer_headers(profile["access_token"]),
        )
        if "error" in out:
            return out
        text = out["data"] if isinstance(out["data"], str) else str(out["data"])
        cap = max(1, min(int(max_chars or 20000), 100000))
        return {"file_id": file_id, "text": text[:cap], "truncated": len(text) > cap}

    box_read_file.__name__ = "box_read_file"
    tools.append(
        _attach(
            box_read_file,
            _schema(
                "box_read_file",
                "Read a text file from Box by file ID.",
                {"file_id": {"type": "string"}, "max_chars": {"type": "integer"}},
                ["file_id"],
            ),
            caps=["box", "read"],
        )
    )
