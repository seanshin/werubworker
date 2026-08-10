"""Figma connector tools."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    _FIGMA = "https://api.figma.com/v1"

    def _figma_headers(profile: dict[str, Any]) -> dict[str, str]:
        return {"X-Figma-Token": str(profile.get("access_token", ""))}

    def _figma_summarize(node: dict[str, Any], depth: int) -> dict[str, Any]:
        out = {
            "id": node.get("id"),
            "name": node.get("name"),
            "type": node.get("type"),
        }
        children = node.get("children") or []
        if depth > 0 and children:
            out["children"] = [_figma_summarize(c, depth - 1) for c in children]
        elif children:
            out["child_count"] = len(children)
        return out

    def figma_get_file(file_key: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "figma", "access_token")
        if err:
            return err
        result = _helpers._request(
            "GET",
            f"{_FIGMA}/files/{quote(file_key)}",
            headers=_figma_headers(profile),
            params={"depth": 2},
        )
        if not result.get("ok"):
            return result
        data = result.get("data") or {}
        # The raw file tree is enormous — return pages + top-level frames only.
        doc = data.get("document") or {}
        return {
            "ok": True,
            "name": data.get("name"),
            "last_modified": data.get("lastModified"),
            "pages": [_figma_summarize(p, 1) for p in (doc.get("children") or [])],
        }

    figma_get_file.__name__ = "figma_get_file"
    tools.append(
        _attach(
            figma_get_file,
            _schema(
                "figma_get_file",
                "Read a Figma file's pages and top-level frames (file key is in the URL).",
                {"file_key": {"type": "string"}},
                ["file_key"],
            ),
            caps=["figma", "read"],
        )
    )

    def figma_get_comments(file_key: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "figma", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_FIGMA}/files/{quote(file_key)}/comments",
            headers=_figma_headers(profile),
        )

    figma_get_comments.__name__ = "figma_get_comments"
    tools.append(
        _attach(
            figma_get_comments,
            _schema(
                "figma_get_comments",
                "List comments on a Figma file.",
                {"file_key": {"type": "string"}},
                ["file_key"],
            ),
            caps=["figma", "read"],
        )
    )

    def figma_post_comment(file_key: str, message: str, reply_to: str = "") -> dict[str, Any]:
        profile, err = _profile(secrets, "figma", "access_token")
        if err:
            return err
        body: dict[str, Any] = {"message": message}
        if reply_to:
            body["comment_id"] = reply_to
        return _helpers._request(
            "POST",
            f"{_FIGMA}/files/{quote(file_key)}/comments",
            headers=_figma_headers(profile),
            json=body,
        )

    figma_post_comment.__name__ = "figma_post_comment"
    tools.append(
        _attach(
            figma_post_comment,
            _schema(
                "figma_post_comment",
                "Comment on a Figma file (optionally replying to a comment). Requires user approval.",
                {
                    "file_key": {"type": "string"},
                    "message": {"type": "string"},
                    "reply_to": {"type": "string"},
                },
                ["file_key", "message"],
            ),
            approval=True,
            caps=["figma", "write"],
        )
    )

    def figma_export_images(
        file_key: str, node_ids: str, format: str = "png", scale: int = 2
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "figma", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_FIGMA}/images/{quote(file_key)}",
            headers=_figma_headers(profile),
            params={"ids": node_ids, "format": format, "scale": scale},
        )

    figma_export_images.__name__ = "figma_export_images"
    tools.append(
        _attach(
            figma_export_images,
            _schema(
                "figma_export_images",
                "Render Figma nodes to image URLs (node ids comma-separated; png/svg/pdf).",
                {
                    "file_key": {"type": "string"},
                    "node_ids": {"type": "string"},
                    "format": {"type": "string"},
                    "scale": {"type": "integer"},
                },
                ["file_key", "node_ids"],
            ),
            caps=["figma", "read"],
        )
    )
