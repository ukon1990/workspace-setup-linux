"""Read-only GitHub Issues adapter backed by the GitHub CLI."""

import sys
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

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
from .references import github_identity, parse_github_references

_LIST_FIELDS = (
    "number,title,state,stateReason,assignees,labels,url,issueType,parent,"
    "blockedBy,blocking"
)
_DETAIL_FIELDS = (
    "number,title,state,stateReason,assignees,labels,url,body,comments,"
    "parent,subIssues,blockedBy,blocking,issueType"
)


class GithubError(RuntimeError):
    """A GitHub CLI operation could not be completed."""


def install_command(platform: Optional[str] = None) -> str:
    """Return the supported install command for the current platform."""
    platform = platform or sys.platform
    if platform == "darwin":
        return "brew install gh"
    return "sudo pacman -S github-cli"


class GithubBackend:
    """Normalize read-only ``gh issue`` responses for the tasks TUI."""

    def __init__(
        self,
        repository: Optional[str] = None,
        *,
        limit: int = 100,
        search: Optional[str] = None,
        timeout: float = 30,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("GitHub issue limit must be an integer from 1 to 1000")
        self.repository = repository
        self.limit = limit
        self.search = search
        self.timeout = timeout

    def validate(self) -> str:
        """Validate ``gh``, authentication, and repository context."""
        self.check_available()
        self.check_auth()
        return self.resolve_repository()

    def check_available(self) -> None:
        try:
            run_text(["gh", "--version"], timeout=self.timeout)
        except ProcessError as error:
            if error.kind is ProcessErrorKind.NOT_FOUND:
                raise GithubError(
                    f"GitHub CLI (gh) is required. Install it with: {install_command()}"
                ) from error
            raise GithubError(f"Could not validate GitHub CLI: {error}") from error

    def check_auth(self) -> None:
        try:
            run_text(
                ["gh", "auth", "status", "--active", "--hostname", "github.com"],
                timeout=self.timeout,
            )
        except ProcessError as error:
            raise GithubError(
                f"GitHub CLI is not authenticated. Run: gh auth login\n{error}"
            ) from error

    def resolve_repository(self) -> str:
        """Return the configured repository or resolve it from the current checkout."""
        if self.repository:
            return self.repository
        try:
            payload = run_json(
                ["gh", "repo", "view", "--json", "nameWithOwner"],
                timeout=self.timeout,
            )
        except ProcessError as error:
            raise GithubError(
                "Could not resolve the current GitHub repository. "
                "Run inside a GitHub checkout or pass --repo owner/repo."
            ) from error
        repository = payload.get("nameWithOwner") if isinstance(payload, dict) else None
        if not isinstance(repository, str) or "/" not in repository:
            raise GithubError("gh repo view returned an invalid repository")
        self.repository = repository
        return repository

    def list_issues(
        self,
        search: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        updated_since: Optional[str] = None,
        include_closed: bool = False,
    ) -> Tuple[TaskSummary, ...]:
        """List bounded issues, optionally delta-filtered by update time."""
        repository = self.resolve_repository()
        query = _join_search(self.search, search)
        if updated_since:
            query = _join_search(query, f"updated:>={updated_since}")
        return self._list_issues(
            repository, query, assignee_filter, include_closed=include_closed
        )

    def _list_issues(
        self,
        repository: str,
        query: Optional[str],
        assignee_filter: AssigneeFilter,
        *,
        include_closed: bool = False,
    ) -> Tuple[TaskSummary, ...]:
        if assignee_filter is AssigneeFilter.UNASSIGNED:
            query = _join_search(query, "no:assignee")
        elif assignee_filter is AssigneeFilter.ASSIGNED_ANYONE:
            query = _join_search(query, "assignee:*")
        elif assignee_filter is AssigneeFilter.ME_OR_UNASSIGNED:
            query = _join_search(query, "(assignee:@me OR no:assignee)")

        command = [
            "gh",
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "all" if include_closed else "open",
            "--limit",
            str(self.limit),
            "--json",
            _LIST_FIELDS,
        ]
        if assignee_filter is AssigneeFilter.ME:
            command.extend(["--assignee", "@me"])
        if query:
            command.extend(["--search", query])
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError as error:
            raise GithubError(f"Could not list GitHub issues for {repository}: {error}") from error
        if not isinstance(payload, list):
            raise GithubError("gh issue list returned invalid JSON")
        return tuple(_normalize_summary(issue, repository) for issue in payload)

    def search_issues(
        self,
        text: str,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        updated_since: Optional[str] = None,
        include_closed: bool = False,
    ) -> Tuple[TaskSummary, ...]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("GitHub search text must be non-empty")
        return self.list_issues(
            text.strip(),
            assignee_filter,
            updated_since=updated_since,
            include_closed=include_closed,
        )

    def get_issue(self, target: Union[str, int, BackendIdentity]) -> TaskDetail:
        """Fetch and normalize one issue without eagerly resolving its relations."""
        identity = self._identity(target)
        command = [
            "gh",
            "issue",
            "view",
            identity.key,
            "--repo",
            identity.repository or "",
            "--json",
            _DETAIL_FIELDS,
        ]
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError as error:
            raise GithubError(
                f"Could not load GitHub issue {identity.display_key}: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise GithubError(f"gh issue view returned invalid JSON for {identity.display_key}")
        return _normalize_detail(payload, identity.repository or "")

    def _identity(self, target: Union[str, int, BackendIdentity]) -> BackendIdentity:
        if isinstance(target, BackendIdentity):
            if target.repository:
                return target
            raise GithubError("GitHub issue identity is missing a repository")
        identity = github_identity(str(target))
        if identity:
            return identity
        identity = github_identity(str(target), default_repo=self.resolve_repository())
        if identity is None:
            raise GithubError("GitHub issue must be a number, owner/repo#number, or issue URL")
        return identity


def _normalize_summary(payload: Any, repository: str) -> TaskSummary:
    issue = _mapping(payload, "GitHub issue")
    number = _positive_int(issue.get("number"), "GitHub issue number")
    title = _string(issue.get("title"), "Untitled issue")
    url = _optional_string(issue.get("url"))
    identity = BackendIdentity.github(number, repository, url=url)
    parent = None
    raw_parent = issue.get("parent")
    if raw_parent is not None:
        parent = _related_identity(_mapping(raw_parent, "GitHub parent"), repository)
    return TaskSummary(
        identity=identity,
        title=title,
        status=_status(issue),
        task_type=_issue_type(issue.get("issueType")),
        assignees=_names(issue.get("assignees")),
        labels=_names(issue.get("labels")),
        url=url,
        parent=parent,
        blocked_by=_related_identities(issue.get("blockedBy"), repository),
        blocks=_related_identities(issue.get("blocking"), repository),
    )


def _related_identities(value: Any, repository: str) -> Tuple[BackendIdentity, ...]:
    identities: List[BackendIdentity] = []
    seen: set[str] = set()
    for item in _items(value):
        identity = _related_identity(_mapping(item, "GitHub issue relationship"), repository)
        if identity is None or identity.stable_id in seen:
            continue
        seen.add(identity.stable_id)
        identities.append(identity)
    return tuple(identities)


def _normalize_detail(payload: Mapping[str, Any], repository: str) -> TaskDetail:
    summary = _normalize_summary(payload, repository)
    comments = tuple(_normalize_comment(item) for item in _items(payload.get("comments")))
    relationships = _relationships(payload, summary.identity, comments)
    return TaskDetail(
        summary=summary,
        description=_string(payload.get("body"), ""),
        comments=comments,
        relationships=relationships,
    )


def _normalize_comment(payload: Any) -> Comment:
    item = _mapping(payload, "GitHub comment")
    author = item.get("author")
    if isinstance(author, dict):
        author_name = _string(author.get("login") or author.get("name"), "unknown")
    else:
        author_name = _string(author, "unknown")
    return Comment(
        author=author_name,
        body=_string(item.get("body"), ""),
        created_at=_optional_string(item.get("createdAt")),
        url=_optional_string(item.get("url")),
    )


def _relationships(
    payload: Mapping[str, Any],
    current: BackendIdentity,
    comments: Sequence[Comment],
) -> Tuple[TaskRelationship, ...]:
    relationships: List[TaskRelationship] = []
    first_class_seen = set()
    seen_targets = {current.stable_id}

    first_class = (
        ("parent", RelationshipKind.PARENT, "parent"),
        ("subIssues", RelationshipKind.CHILD, "sub-issue"),
        ("blockedBy", RelationshipKind.BLOCKED_BY, "blocked by"),
        ("blocking", RelationshipKind.BLOCKS, "blocks"),
    )
    for field, kind, label in first_class:
        for item in _items(payload.get(field)):
            relation = _first_class_relationship(
                item,
                default_repo=current.repository or "",
                kind=kind,
                label=label,
            )
            if relation is None:
                continue
            key = (relation.kind, relation.target.stable_id)
            seen_targets.add(relation.target.stable_id)
            if key in first_class_seen:
                continue
            first_class_seen.add(key)
            relationships.append(relation)

    texts = [_string(payload.get("body"), "")]
    texts.extend(comment.body for comment in comments)
    for text in texts:
        for reference in parse_github_references(
            text,
            default_repo=current.repository,
            current=current,
        ):
            if reference.target.stable_id not in seen_targets:
                seen_targets.add(reference.target.stable_id)
                relationships.append(
                    TaskRelationship(
                        RelationshipKind.MENTIONED,
                        reference.target,
                        "mentioned",
                    )
                )
    return tuple(relationships)


def _first_class_relationship(
    payload: Any,
    *,
    default_repo: str,
    kind: RelationshipKind,
    label: str,
) -> Optional[TaskRelationship]:
    item = _mapping(payload, "GitHub issue relationship")
    identity = _related_identity(item, default_repo)
    if identity is None:
        return None
    return TaskRelationship(
        kind=kind,
        target=identity,
        label=label,
        summary=_optional_string(item.get("title")),
    )


def _related_identity(payload: Mapping[str, Any], default_repo: str) -> Optional[BackendIdentity]:
    url = _optional_string(payload.get("url"))
    if url:
        identity = github_identity(url)
        if identity:
            return identity

    repository = payload.get("repository")
    if isinstance(repository, dict):
        repository = repository.get("nameWithOwner")
    repository = _optional_string(repository) or default_repo
    number = payload.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        return None
    return BackendIdentity.github(number, repository, url=url)


def _items(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("nodes"), list):
        return value["nodes"]
    return (value,)


def _names(value: Any) -> Tuple[str, ...]:
    names = []
    for item in _items(value):
        if isinstance(item, dict):
            name = item.get("login") or item.get("name")
        else:
            name = item
        if isinstance(name, str) and name:
            names.append(name)
    return tuple(names)


def _status(issue: Mapping[str, Any]) -> str:
    reason = _optional_string(issue.get("stateReason"))
    state = _string(issue.get("state"), "UNKNOWN")
    return reason.replace("_", " ").title() if reason else state.replace("_", " ").title()


def _issue_type(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name")
    return value.strip() if isinstance(value, str) and value.strip() else "Issue"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise GithubError(f"{name} data is invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GithubError(f"{name} is invalid")
    return value


def _string(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _join_search(configured: Optional[str], requested: Optional[str]) -> Optional[str]:
    parts = [part.strip() for part in (configured, requested) if part and part.strip()]
    return " ".join(parts) or None
