"""GitLab connector tools."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _clamp, _gitlab_api, _profile, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def gitlab_search(
        query: str, scope: str = "issues", max_results: int = 10
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "gitlab", "token")
        if err:
            return err
        kind = scope if scope in ("projects", "issues", "merge_requests") else "issues"
        return _helpers._request(
            "GET",
            f"{_gitlab_api(profile)}/search",
            headers={"PRIVATE-TOKEN": profile["token"]},
            params={"scope": kind, "search": query, "per_page": _clamp(max_results)},
        )

    gitlab_search.__name__ = "gitlab_search"
    tools.append(
        _attach(
            gitlab_search,
            _schema(
                "gitlab_search",
                "Search GitLab projects, issues, or merge_requests (scope).",
                {
                    "query": {"type": "string"},
                    "scope": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["query"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_get_issue(project: str, issue_iid: int) -> dict[str, Any]:
        profile, err = _profile(secrets, "gitlab", "token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_gitlab_api(profile)}/projects/{quote(project, safe='')}/issues/{issue_iid}",
            headers={"PRIVATE-TOKEN": profile["token"]},
        )

    gitlab_get_issue.__name__ = "gitlab_get_issue"
    tools.append(
        _attach(
            gitlab_get_issue,
            _schema(
                "gitlab_get_issue",
                "Read a GitLab issue. project is an ID or full path like group/repo.",
                {"project": {"type": "string"}, "issue_iid": {"type": "integer"}},
                ["project", "issue_iid"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_get_merge_request(project: str, mr_iid: int) -> dict[str, Any]:
        profile, err = _profile(secrets, "gitlab", "token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_gitlab_api(profile)}/projects/{quote(project, safe='')}/merge_requests/{mr_iid}",
            headers={"PRIVATE-TOKEN": profile["token"]},
        )

    gitlab_get_merge_request.__name__ = "gitlab_get_merge_request"
    tools.append(
        _attach(
            gitlab_get_merge_request,
            _schema(
                "gitlab_get_merge_request",
                "Read a GitLab merge request. project is an ID or full path like group/repo.",
                {"project": {"type": "string"}, "mr_iid": {"type": "integer"}},
                ["project", "mr_iid"],
            ),
            caps=["gitlab", "read"],
        )
    )

    def gitlab_create_issue(
        project: str, title: str, description: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "gitlab", "token")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"{_gitlab_api(profile)}/projects/{quote(project, safe='')}/issues",
            headers={"PRIVATE-TOKEN": profile["token"]},
            json={"title": title, "description": description},
        )

    gitlab_create_issue.__name__ = "gitlab_create_issue"
    tools.append(
        _attach(
            gitlab_create_issue,
            _schema(
                "gitlab_create_issue",
                "Create a GitLab issue. Requires user approval.",
                {
                    "project": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["project", "title"],
            ),
            approval=True,
            caps=["gitlab", "write"],
        )
    )
