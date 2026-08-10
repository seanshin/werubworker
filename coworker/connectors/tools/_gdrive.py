"""Google Drive connector tools (read-only; deliberately no write scope)."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _GEN_ACCOUNT_PROP,
    _account_profile,
    _acct_result,
    _attach,
    _clamp,
    _google_headers,
    _schema,
)


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    _DRIVE = "https://www.googleapis.com/drive/v3"
    _DRIVE_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink)"
    # Google-native types export to text; everything else downloads as-is.
    _DRIVE_EXPORTS = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.presentation": "text/plain",
    }

    def _drive_quote(term: str) -> str:
        return term.replace("\\", "\\\\").replace("'", "\\'")

    def drive_search_files(query: str, max_results: int = 10, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "google_drive", account, "access_token")
        if err:
            return err
        q = _drive_quote(query)
        return _acct_result(
            aid,
            _helpers._request(
                "GET",
                f"{_DRIVE}/files",
                headers=_google_headers(profile["access_token"]),
                params={
                    "q": f"(name contains '{q}' or fullText contains '{q}') and trashed=false",
                    "pageSize": _clamp(max_results),
                    "fields": _DRIVE_FIELDS,
                },
            ),
        )

    drive_search_files.__name__ = "drive_search_files"
    tools.append(
        _attach(
            drive_search_files,
            _schema(
                "drive_search_files",
                "Search Google Drive files by name or content.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["google_drive", "read"],
        )
    )

    def drive_list_folder(
        folder_id: str = "root", max_results: int = 20, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "google_drive", account, "access_token")
        if err:
            return err
        return _acct_result(
            aid,
            _helpers._request(
                "GET",
                f"{_DRIVE}/files",
                headers=_google_headers(profile["access_token"]),
                params={
                    "q": f"'{_drive_quote(folder_id)}' in parents and trashed=false",
                    "pageSize": _clamp(max_results, default=20, ceiling=50),
                    "fields": _DRIVE_FIELDS,
                },
            ),
        )

    drive_list_folder.__name__ = "drive_list_folder"
    tools.append(
        _attach(
            drive_list_folder,
            _schema(
                "drive_list_folder",
                "List a Google Drive folder's contents ('root' for My Drive).",
                {
                    "folder_id": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["google_drive", "read"],
        )
    )

    def drive_read_file(file_id: str, max_chars: int = 20000, account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "google_drive", account, "access_token")
        if err:
            return err
        headers = _google_headers(profile["access_token"])
        meta = _helpers._request(
            "GET",
            f"{_DRIVE}/files/{quote(file_id)}",
            headers=headers,
            params={"fields": "id,name,mimeType,size"},
        )
        if not meta.get("ok"):
            return _acct_result(aid, meta)
        info = meta.get("data") or {}
        mime = str(info.get("mimeType", ""))
        export_mime = _DRIVE_EXPORTS.get(mime)
        if export_mime:
            body = _helpers._request(
                "GET",
                f"{_DRIVE}/files/{quote(file_id)}/export",
                headers=headers,
                params={"mimeType": export_mime},
            )
        elif mime.startswith("application/vnd.google-apps"):
            return _acct_result(aid, {"error": f"cannot read {mime} as text", "file": info})
        else:
            body = _helpers._request(
                "GET",
                f"{_DRIVE}/files/{quote(file_id)}",
                headers=headers,
                params={"alt": "media"},
            )
        if not body.get("ok"):
            return _acct_result(aid, body)
        text = body.get("data")
        if not isinstance(text, str):
            text = json.dumps(text)
        return _acct_result(
            aid,
            {
                "ok": True,
                "file": info,
                "content": text[: max(1, int(max_chars))],
                "truncated": len(text) > max_chars,
            },
        )

    drive_read_file.__name__ = "drive_read_file"
    tools.append(
        _attach(
            drive_read_file,
            _schema(
                "drive_read_file",
                "Read a Drive file as text (Docs/Sheets/Slides export; other text files download).",
                {
                    "file_id": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["file_id"],
            ),
            caps=["google_drive", "read"],
        )
    )
