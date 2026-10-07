"""Native child inventories and exhaustive Jira parent searches."""

import re
from dataclasses import replace
from typing import Any, Mapping, Sequence

from .backend_updates import _jira_complete
from .models import Backend, BackendIdentity, ChildrenBatch
from .process import ProcessError, run_json

_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
_GITHUB_CHILD_CAP = 100


def github_children(issue: Mapping[str, Any], repository: str):
    from .github import _related_identity

    value = issue.get("subIssues")
    complete = True
    explicit_end = False
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("nodes"), list):
        rows = value["nodes"]
        page = value.get("pageInfo")
        if page is not None:
            if not isinstance(page, dict) or page.get("hasNextPage") is not False:
                complete = False
            else:
                explicit_end = True
        total = value.get("totalCount")
        if total is not None:
            if not isinstance(total, int) or isinstance(total, bool) or total != len(rows):
                complete = False
            else:
                explicit_end = True
    else:
        return (), False
    if len(rows) >= _GITHUB_CHILD_CAP and not explicit_end:
        complete = False
    children = {}
    for row in rows:
        child = _related_identity(row, repository) if isinstance(row, dict) else None
        if child is None or child.stable_id in children:
            complete = False
            continue
        children[child.stable_id] = child
    return tuple(children.values()), complete


def jira_child_metadata(fields: Mapping[str, Any]):
    from .jira import _link_identity

    children = {}
    rows = fields.get("subtasks")
    if isinstance(rows, list):
        for row in rows:
            child = _link_identity(row) if isinstance(row, dict) else None
            if child is not None:
                children[child.stable_id] = child
    issue_type = fields.get("issuetype", fields.get("issueType"))
    # Jira's subtasks field omits epic/story children; only native subtasks are leaves.
    leaf = isinstance(issue_type, dict) and issue_type.get("subtask") is True
    valid = rows is None or (isinstance(rows, list) and len(children) == len(rows))
    return tuple(children.values()), leaf and not children and valid


def jira_children(parents: Sequence[BackendIdentity], *, timeout: float = 30) -> ChildrenBatch:
    from .jira import _SEARCH_FIELDS, JiraError, _search_items, _summary

    parent_map = {}
    for parent in parents:
        if parent.backend is not Backend.JIRA or not _JIRA_KEY.fullmatch(parent.key):
            raise ValueError("Jira child lookup requires Jira parent identities")
        parent_map[parent.stable_id] = parent
    if not parent_map:
        return ChildrenBatch()
    keys = ", ".join(parent.key for parent in parent_map.values())
    jql = f"parent IN ({keys}) ORDER BY key ASC"
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
        raise JiraError("Could not load Jira child issues.", error) from error
    rows = _search_items(payload)
    complete = _jira_complete(payload, len(rows))
    items = {}
    for row in rows:
        child = _summary(row)
        parent = child.parent
        if parent is None and len(parent_map) == 1:
            parent = next(iter(parent_map.values()))
        if parent is None or parent.stable_id not in parent_map:
            complete = False
            continue
        child = replace(child, parent=parent_map[parent.stable_id])
        items[child.identity.stable_id] = child
    return ChildrenBatch(tuple(items.values()), complete and len(items) == len(rows))
