"""Attio connector tools."""

from __future__ import annotations

import json
from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _GEN_ACCOUNT_PROP,
    _account_profile,
    _acct_result,
    _attach,
    _bearer_headers,
    _clamp,
    _schema,
)


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def attio_list_objects(account: str = "") -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "attio", account, "access_token")
        if err:
            return err
        result = _helpers._request(
            "GET",
            "https://api.attio.com/v2/objects",
            headers=_bearer_headers(profile["access_token"]),
        )
        return _acct_result(aid, result)

    attio_list_objects.__name__ = "attio_list_objects"
    tools.append(
        _attach(
            attio_list_objects,
            _schema(
                "attio_list_objects",
                "List Attio object types (companies, people, deals, custom).",
                {"account": _GEN_ACCOUNT_PROP},
                [],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_query_records(
        object_type: str,
        filter_json: str = "",
        max_results: int = 10,
        account: str = "",
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "attio", account, "access_token")
        if err:
            return err
        body: dict[str, Any] = {"limit": _clamp(max_results, ceiling=100)}
        if filter_json:
            try:
                body["filter"] = json.loads(filter_json)
            except ValueError:
                return {"error": "filter_json must be an Attio filter object (JSON)"}
        result = _helpers._request(
            "POST",
            f"https://api.attio.com/v2/objects/{object_type}/records/query",
            headers=_bearer_headers(profile["access_token"]),
            json=body,
        )
        return _acct_result(aid, result)

    attio_query_records.__name__ = "attio_query_records"
    tools.append(
        _attach(
            attio_query_records,
            _schema(
                "attio_query_records",
                "List/filter records of an Attio object (e.g. companies, people); "
                "filter_json is an Attio filter object.",
                {
                    "object_type": {"type": "string"},
                    "filter_json": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["object_type"],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_get_record(
        object_type: str, record_id: str, account: str = ""
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "attio", account, "access_token")
        if err:
            return err
        result = _helpers._request(
            "GET",
            f"https://api.attio.com/v2/objects/{object_type}/records/{record_id}",
            headers=_bearer_headers(profile["access_token"]),
        )
        return _acct_result(aid, result)

    attio_get_record.__name__ = "attio_get_record"
    tools.append(
        _attach(
            attio_get_record,
            _schema(
                "attio_get_record",
                "Read one Attio record by object type and record id.",
                {
                    "object_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["object_type", "record_id"],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_create_note(
        parent_object: str,
        parent_record_id: str,
        title: str,
        content: str,
        account: str = "",
    ) -> dict[str, Any]:
        aid, profile, err = _account_profile(secrets, "attio", account, "access_token")
        if err:
            return err
        result = _helpers._request(
            "POST",
            "https://api.attio.com/v2/notes",
            headers=_bearer_headers(profile["access_token"]),
            json={
                "data": {
                    "parent_object": parent_object,
                    "parent_record_id": parent_record_id,
                    "title": title,
                    "format": "plaintext",
                    "content": content,
                }
            },
        )
        return _acct_result(aid, result)

    attio_create_note.__name__ = "attio_create_note"
    tools.append(
        _attach(
            attio_create_note,
            _schema(
                "attio_create_note",
                "Log a note on an Attio record (e.g. a company or person).",
                {
                    "parent_object": {"type": "string"},
                    "parent_record_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "account": _GEN_ACCOUNT_PROP,
                },
                ["parent_object", "parent_record_id", "title", "content"],
            ),
            approval=True,
            caps=["attio", "write"],
        )
    )
