"""Read-only Jira backend powered by Atlassian CLI."""

import re
import sys
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from .config import JiraConfig
from .filters import AssigneeFilter
from .models import (
    BackendIdentity,
    Comment,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)
from .process import ProcessError, ProcessErrorKind, run_json, run_text
from .references import jira_identity, parse_jira_references

_PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
_LUCENE_RESERVED_RE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')
_SEARCH_FIELDS = "key,issuetype,summary,status,assignee,priority"
_DETAIL_FIELDS = (
    "key,issuetype,summary,status,assignee,priority,labels,components,"
    "description,comment,parent,subtasks,issuelinks"
)


class JiraError(RuntimeError):
    """A Jira operation failed without exposing command arguments or credentials."""

    def __init__(self, message: str, process_error: Optional[ProcessError] = None):
        super().__init__(message)
        self.process_error = process_error


class JiraBackend:
    """Normalize read-only Jira work items into the shared task model."""

    def __init__(self, config: Optional[JiraConfig] = None, *, timeout: float = 30):
        self.config = config or JiraConfig()
        self.timeout = timeout

    def validate(self) -> str:
        """Validate ACLI availability/version and Jira authentication."""
        version = self.check_available()
        self.check_auth()
        return version

    def check_available(self) -> str:
        try:
            output = run_text(["acli", "--version"], timeout=self.timeout).strip()
        except ProcessError as error:
            if error.kind is ProcessErrorKind.NOT_FOUND:
                raise JiraError(_missing_acli_guidance(), error) from error
            raise JiraError(
                "Could not validate Atlassian CLI. Run `acli --version`.", error
            ) from error
        match = _VERSION_RE.search(output)
        if not match:
            error = ProcessError(
                ProcessErrorKind.FAILED,
                "acli",
                "Atlassian CLI returned an unrecognized version",
            )
            raise JiraError(
                "The installed `acli` returned an unrecognized version. "
                "Update it using Atlassian's official installation instructions.",
                error,
            ) from error
        return match.group(0)

    def check_auth(self) -> None:
        try:
            output = run_text(["acli", "jira", "auth", "status"], timeout=self.timeout).strip()
        except ProcessError as error:
            raise JiraError(
                "Jira authentication is required. Run `acli jira auth login`, then retry.",
                error,
            ) from error
        if re.search(
            r"(?i)(not authenticated|authenticated\s*[:|]\s*no|no jira accounts?)",
            output,
        ):
            error = ProcessError(
                ProcessErrorKind.FAILED,
                "acli",
                "Atlassian CLI reports no authenticated Jira account",
            )
            raise JiraError(
                "Jira authentication is required. Run `acli jira auth login`, then retry.",
                error,
            ) from error

    def list_tasks(
        self,
        project: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        jql_extra: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    ) -> Tuple[TaskSummary, ...]:
        """List a bounded set of non-Done work items in one Jira project."""
        project_key = self._project(project)
        jql = self._jql(project_key, assignee_filter=assignee_filter, extra=jql_extra)
        return self._search(jql, self._limit(limit))

    def search_tasks(
        self,
        project: Optional[str],
        query: str,
        *,
        limit: Optional[int] = None,
        jql_extra: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    ) -> Tuple[TaskSummary, ...]:
        """Search summary and description while retaining the project boundary."""
        if not isinstance(query, str) or not query.strip():
            raise JiraError("Jira search query must be a non-empty string.")
        project_key = self._project(project)
        escaped = _escape_jql_string(query.strip())
        text_clause = f'(summary ~ "{escaped}" OR description ~ "{escaped}")'
        jql = self._jql(
            project_key,
            text_clause=text_clause,
            assignee_filter=assignee_filter,
            extra=jql_extra,
        )
        return self._search(jql, self._limit(limit))

    def get_task(self, value: str) -> TaskDetail:
        """Fetch a Jira work item by key or browse URL."""
        identity = jira_identity(value)
        if identity is None:
            raise JiraError("Expected a Jira key or /browse/KEY URL.")
        try:
            payload = run_json(
                [
                    "acli",
                    "jira",
                    "workitem",
                    "view",
                    identity.key,
                    "--fields",
                    _DETAIL_FIELDS,
                    "--json",
                ],
                timeout=self.timeout,
            )
        except ProcessError as error:
            raise JiraError(f"Could not load Jira work item {identity.key}.", error) from error
        item = _single_item(payload)
        return _detail(item, requested_identity=identity)

    def _search(self, jql: str, limit: int) -> Tuple[TaskSummary, ...]:
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
                    "--limit",
                    str(limit),
                    "--json",
                ],
                timeout=self.timeout,
            )
        except ProcessError as error:
            raise JiraError("Could not search Jira work items.", error) from error
        return tuple(_summary(item) for item in _search_items(payload))

    def _project(self, project: Optional[str]) -> str:
        value = project or self.config.default_project
        if not value:
            raise JiraError("A Jira project is required.")
        if not isinstance(value, str) or not _PROJECT_RE.fullmatch(value):
            raise JiraError("Jira project must be a valid project key.")
        return value.upper()

    def _limit(self, limit: Optional[int]) -> int:
        value = self.config.limit if limit is None else limit
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
            raise JiraError("Jira limit must be an integer from 1 to 1000.")
        return value

    def _jql(
        self,
        project: str,
        *,
        text_clause: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        extra: Optional[str] = None,
    ) -> str:
        clauses = [f'project = "{project}"', "statusCategory != Done"]
        assignee_clause = {
            AssigneeFilter.ALL: None,
            AssigneeFilter.ME: "assignee = currentUser()",
            AssigneeFilter.UNASSIGNED: "assignee is EMPTY",
            AssigneeFilter.ME_OR_UNASSIGNED: (
                "(assignee = currentUser() OR assignee is EMPTY)"
            ),
            AssigneeFilter.ASSIGNED_ANYONE: "assignee is not EMPTY",
        }[assignee_filter]
        if assignee_clause:
            clauses.append(assignee_clause)
        if text_clause:
            clauses.append(text_clause)
        configured_extra = self.config.jql_extra
        for clause in (configured_extra, extra):
            if clause and clause.strip():
                clauses.append(f"({clause.strip()})")
        return " AND ".join(clauses) + " ORDER BY updated DESC"


def _missing_acli_guidance() -> str:
    if sys.platform == "darwin":
        return (
            "`acli` is required. Install Atlassian CLI on macOS with:\n"
            "  brew tap atlassian/homebrew-acli\n"
            "  brew install acli"
        )
    return (
        "`acli` is required. Follow Atlassian's official Linux instructions:\n"
        "  https://developer.atlassian.com/cloud/acli/guides/install-linux/\n"
        "Download the matching binary from https://acli.atlassian.com/linux/latest/, "
        "then install it with `sudo install -o root -g root -m 0755 acli "
        "/usr/local/bin/acli`."
    )


def _escape_jql_string(value: str) -> str:
    lucene_escaped = _LUCENE_RESERVED_RE.sub(r"\\\1", value)
    return lucene_escaped.replace("\\", "\\\\").replace('"', '\\"')


def _search_items(payload: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = next(
            (
                payload[key]
                for key in ("issues", "workItems", "workitems", "results", "values")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        if items is None and _item_key(payload):
            items = [payload]
    else:
        items = None
    if items is None or not all(isinstance(item, dict) for item in items):
        raise JiraError("Atlassian CLI returned an unexpected Jira search response.")
    return items


def _single_item(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, dict) and _item_key(payload):
        return payload
    items = _search_items(payload)
    if len(items) != 1:
        raise JiraError("Atlassian CLI returned an unexpected Jira work item response.")
    return items[0]


def _fields(item: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = item.get("fields")
    if isinstance(nested, dict):
        return {**item, **nested}
    return item


def _item_key(item: Mapping[str, Any]) -> Optional[str]:
    fields = _fields(item)
    key = fields.get("key")
    return key.upper() if isinstance(key, str) and key else None


def _summary(item: Mapping[str, Any], *, fallback_url: Optional[str] = None) -> TaskSummary:
    fields = _fields(item)
    key = _item_key(item)
    if not key:
        raise JiraError("Atlassian CLI returned a Jira work item without a key.")
    url = _browse_url(item, key) or fallback_url
    return TaskSummary(
        identity=BackendIdentity.jira(key, url=url),
        title=_text_value(fields.get("summary")) or "(untitled)",
        status=_named(fields.get("status")) or "Unknown",
        task_type=_named(fields.get("issuetype") or fields.get("issueType")),
        priority=_named(fields.get("priority")),
        assignees=_assignees(fields.get("assignee")),
        labels=_string_tuple(fields.get("labels")),
        components=_named_tuple(fields.get("components")),
        url=url,
    )


def _detail(
    item: Mapping[str, Any], *, requested_identity: Optional[BackendIdentity] = None
) -> TaskDetail:
    fields = _fields(item)
    summary = _summary(item, fallback_url=requested_identity.url if requested_identity else None)
    description = _adf_text(fields.get("description"))
    comments = _comments(fields.get("comment") or fields.get("comments"))
    relationships = list(_first_class_relationships(fields))
    occupied = {summary.identity.stable_id}
    occupied.update(relation.target.stable_id for relation in relationships)
    mention_text = "\n".join([description, *(comment.body for comment in comments)])
    for reference in parse_jira_references(mention_text, current=summary.identity):
        if reference.target.stable_id not in occupied:
            occupied.add(reference.target.stable_id)
            relationships.append(
                TaskRelationship(
                    RelationshipKind.MENTIONED,
                    reference.target,
                    "mentioned",
                )
            )
    return TaskDetail(summary, description, comments, tuple(relationships))


def _comments(value: Any) -> Tuple[Comment, ...]:
    if isinstance(value, dict):
        value = value.get("comments") or value.get("values") or []
    if not isinstance(value, list):
        return ()
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        result.append(
            Comment(
                author=_named(author) or "Unknown",
                body=_adf_text(item.get("body")),
                created_at=_text_value(item.get("created") or item.get("createdAt")),
                url=_text_value(item.get("url") or item.get("self")),
            )
        )
    return tuple(result)


def _first_class_relationships(fields: Mapping[str, Any]) -> Iterable[TaskRelationship]:
    parent = fields.get("parent")
    if isinstance(parent, dict):
        relation = _relationship(parent, RelationshipKind.PARENT, "parent")
        if relation:
            yield relation
    subtasks = fields.get("subtasks")
    if isinstance(subtasks, list):
        for subtask in subtasks:
            if isinstance(subtask, dict):
                relation = _relationship(subtask, RelationshipKind.CHILD, "subtask")
                if relation:
                    yield relation
    links = fields.get("issuelinks") or fields.get("issueLinks")
    if not isinstance(links, list):
        return
    for link in links:
        if not isinstance(link, dict):
            continue
        link_type = link.get("type") if isinstance(link.get("type"), dict) else {}
        outward = link.get("outwardIssue")
        inward = link.get("inwardIssue")
        if isinstance(outward, dict):
            label = _text_value(link_type.get("outward")) or "relates to"
            relation = _relationship(outward, _relationship_kind(label), label)
            if relation:
                yield relation
        if isinstance(inward, dict):
            label = _text_value(link_type.get("inward")) or "relates to"
            relation = _relationship(inward, _relationship_kind(label), label)
            if relation:
                yield relation


def _relationship(
    item: Mapping[str, Any], kind: RelationshipKind, label: str
) -> Optional[TaskRelationship]:
    key = _item_key(item)
    if not key:
        return None
    fields = _fields(item)
    return TaskRelationship(
        kind,
        BackendIdentity.jira(key, url=_browse_url(item, key)),
        label,
        _text_value(fields.get("summary")),
    )


def _relationship_kind(label: str) -> RelationshipKind:
    normalized = label.casefold()
    if normalized == "blocks" or normalized.startswith("blocks "):
        return RelationshipKind.BLOCKS
    if "blocked by" in normalized:
        return RelationshipKind.BLOCKED_BY
    return RelationshipKind.RELATED


def _browse_url(item: Mapping[str, Any], key: str) -> Optional[str]:
    fields = _fields(item)
    for candidate in (
        fields.get("browseUrl"),
        fields.get("webUrl"),
        fields.get("url"),
        item.get("browseUrl"),
        item.get("webUrl"),
    ):
        if isinstance(candidate, str) and "/browse/" in candidate:
            return candidate
    self_url = item.get("self")
    if isinstance(self_url, str):
        match = re.match(r"(https?://[^/]+)/", self_url)
        if match:
            return f"{match.group(1)}/browse/{key}"
    return None


def _adf_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _join_blocks(_adf_text(item) for item in value)
    if not isinstance(value, dict):
        return str(value)

    node_type = value.get("type")
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    if node_type == "text":
        text = _text_value(value.get("text")) or ""
        link = next(
            (
                mark.get("attrs", {}).get("href")
                for mark in value.get("marks", [])
                if isinstance(mark, dict)
                and mark.get("type") == "link"
                and isinstance(mark.get("attrs"), dict)
            ),
            None,
        )
        return f"{text} ({link})" if link and link not in text else text
    if node_type == "hardBreak":
        return "\n"
    if node_type in {"mention", "emoji", "status"}:
        return (
            _text_value(attrs.get("text") or attrs.get("displayName") or attrs.get("shortName"))
            or ""
        )
    if node_type in {"inlineCard", "blockCard", "embedCard"}:
        return _text_value(attrs.get("url")) or ""

    content = value.get("content")
    if not isinstance(content, list):
        return ""
    parts = [_adf_text(item) for item in content]
    if node_type in {
        "doc",
        "blockquote",
        "bulletList",
        "orderedList",
        "table",
        "tableRow",
    }:
        rendered = _join_blocks(parts)
    else:
        rendered = _join_inline(parts)
    if node_type == "listItem":
        return f"- {rendered.strip()}"
    if node_type == "codeBlock":
        return rendered.strip("\n")
    return rendered


def _join_inline(parts: Iterable[str]) -> str:
    output = ""
    for part in parts:
        if not part:
            continue
        if (
            output
            and not output.endswith(("\n", " "))
            and not part.startswith(("\n", " ", ".", ","))
        ):
            output += " "
        output += part
    return output.strip()


def _join_blocks(parts: Iterable[str]) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _named(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key"):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
    return None


def _text_value(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _assignees(value: Any) -> Tuple[str, ...]:
    if isinstance(value, list):
        return tuple(name for item in value if (name := _named(item)))
    name = _named(value)
    return (name,) if name else ()


def _string_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _named_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(name for item in value if (name := _named(item)))
