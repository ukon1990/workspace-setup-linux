"""Scope-wide update feeds kept separate from filtered browser searches."""

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .models import TaskSummary, UpdateBatch
from .process import ProcessError, run_json

_GITHUB_SCOPE = re.compile(r"^github:([^/:\s]+/[^/:\s]+)$")
_JIRA_SCOPE = re.compile(r"^jira:([A-Z][A-Z0-9_]*)$")
_PAGE_SIZE = 100
_MAX_SEARCH_PAGES = 10
_OVERLAP = timedelta(minutes=5)


def _since_datetime(since: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Update checkpoint must be an ISO timestamp") from error
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def github_updates(scope: str, since: str, *, timeout: float = 30) -> UpdateBatch:
    from .github import GithubError, _normalize_summary

    match = _GITHUB_SCOPE.fullmatch(scope)
    if match is None:
        raise ValueError("GitHub update scope must be github:owner/repository")
    repository = match[1]
    lower = (_since_datetime(since) - _OVERLAP).isoformat().replace("+00:00", "Z")
    query = f"repo:{repository} is:issue updated:>={lower}"
    items: dict[str, TaskSummary] = {}
    complete = True
    expected = 0
    received = 0
    for page in range(1, _MAX_SEARCH_PAGES + 1):
        try:
            payload = run_json(
                [
                    "gh",
                    "api",
                    "search/issues",
                    "--method",
                    "GET",
                    "-f",
                    f"q={query}",
                    "-f",
                    "sort=updated",
                    "-f",
                    "order=asc",
                    "-F",
                    f"per_page={_PAGE_SIZE}",
                    "-F",
                    f"page={page}",
                ],
                timeout=timeout,
            )
        except ProcessError as error:
            raise GithubError(f"Could not load GitHub updates for {repository}: {error}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise GithubError("GitHub update search returned invalid JSON")
        total = payload.get("total_count")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            expected = max(expected, total)
        else:
            complete = False
        if payload.get("incomplete_results") is not False:
            complete = False
        rows = payload["items"]
        received += len(rows)
        for row in rows:
            if not isinstance(row, dict) or "pull_request" in row:
                complete = False
                continue
            try:
                # REST search provides state and updated time, but no dependency graph.
                task = _normalize_summary(
                    {
                        "number": row.get("number"),
                        "title": row.get("title"),
                        "state": row.get("state"),
                        "stateReason": row.get("state_reason"),
                        "assignees": row.get("assignees"),
                        "labels": row.get("labels"),
                        "url": row.get("html_url"),
                        "issueType": row.get("type"),
                        "updatedAt": row.get("updated_at"),
                    },
                    repository,
                )
            except GithubError:
                complete = False
                continue
            if task.updated_at is None:
                complete = False
            items[task.identity.stable_id] = task
        if len(rows) < _PAGE_SIZE or received >= expected:
            break
    complete = complete and len(items) >= expected
    return UpdateBatch(tuple(items.values()), complete)


def jira_updates(scope: str, since: str, *, timeout: float = 30) -> UpdateBatch:
    from .jira import _SEARCH_FIELDS, JiraError, _search_items, _summary

    match = _JIRA_SCOPE.fullmatch(scope)
    if match is None:
        raise ValueError("Jira update scope must be jira:PROJECT")
    elapsed = datetime.now(timezone.utc) - _since_datetime(since)
    minutes = max(0, math.ceil(elapsed.total_seconds() / 60)) + 5
    jql = f'project = "{match[1]}" AND updated >= "-{minutes}m" ORDER BY updated ASC'
    try:
        payload = run_json(
            [
                "acli",
                "jira",
                "workitem",
                "search",
                "--jql",
                jql,
                "--fields",
                _SEARCH_FIELDS,
                "--paginate",
                "--json",
            ],
            timeout=timeout,
        )
    except ProcessError as error:
        raise JiraError(f"Could not load Jira updates for {match[1]}.", error) from error
    rows = _search_items(payload)
    items = {}
    for row in rows:
        task = _summary(row)
        items[task.identity.stable_id] = task
    complete = _jira_complete(payload, len(items)) and all(
        task.updated_at is not None for task in items.values()
    )
    return UpdateBatch(tuple(items.values()), complete)


def _jira_complete(payload: Any, count: int) -> bool:
    # ACLI --paginate normally emits a flat array of all pages.
    if isinstance(payload, list):
        return True
    if not isinstance(payload, Mapping):
        return False
    if (
        payload.get("isLast") is False
        or payload.get("hasMore")
        or payload.get("hasNextPage")
        or payload.get("nextPageToken")
    ):
        return False
    total = payload.get("total", payload.get("totalCount"))
    if total is not None and (
        not isinstance(total, int) or isinstance(total, bool) or count < total
    ):
        return False
    for key in ("pagination", "pageInfo"):
        if key in payload and not _jira_complete(payload[key], count):
            return False
    return not payload.get("incomplete_results", False)
