"""Read-only GitHub Pull Requests adapter backed by the GitHub CLI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from rich.text import Text

from .filters import AssigneeFilter
from .models import CiCheck, CiState, Comment, PullDetail, PullSummary, ReviewComment
from .process import ProcessError, ProcessErrorKind, run_json, run_text

_LIST_FIELDS = (
    "number,title,state,isDraft,author,assignees,labels,url,updatedAt,"
    "reviewDecision,statusCheckRollup"
)
_DETAIL_FIELDS = (
    "number,title,state,isDraft,author,assignees,labels,url,body,comments,"
    "reviewDecision,statusCheckRollup,baseRefName,headRefName"
)

_CI_RANK = {
    CiState.FAIL: 0,
    CiState.PENDING: 1,
    CiState.CANCEL: 2,
    CiState.SKIPPING: 3,
    CiState.UNKNOWN: 4,
    CiState.PASS: 5,
}


class PullsError(RuntimeError):
    """A GitHub pull-request CLI operation could not be completed."""


def resolve_github_repository(
    *,
    explicit: Optional[str] = None,
    config_default: Optional[str] = None,
    timeout: float = 30,
) -> Optional[str]:
    """Resolve owner/repo from flag, config, or ``gh repo view``."""
    for candidate in (explicit, config_default):
        if isinstance(candidate, str) and "/" in candidate.strip():
            return candidate.strip().lower()
    try:
        payload = run_json(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            timeout=timeout,
        )
    except ProcessError:
        return None
    name = payload.get("nameWithOwner") if isinstance(payload, dict) else None
    if isinstance(name, str) and "/" in name:
        return name.lower()
    return None


def ci_state_rank(state: CiState) -> int:
    return _CI_RANK.get(state, 4)


@dataclass(frozen=True)
class DiffFile:
    path: str
    label: str
    hunk: str
    added: int = 0
    deleted: int = 0
    excluded: bool = False

    @property
    def net(self) -> int:
        return self.added + self.deleted


def count_diff_lines(hunk: str) -> Tuple[int, int]:
    added = deleted = 0
    for line in hunk.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def path_is_excluded(path: str, patterns: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized or not patterns:
        return False
    name = PurePosixPath(normalized).name
    for pattern in patterns:
        cleaned = pattern.replace("\\", "/").strip()
        if not cleaned:
            continue
        candidates = (cleaned,)
        if cleaned.startswith("**/"):
            candidates = (cleaned, cleaned[3:])
        matched = False
        for candidate in candidates:
            try:
                if PurePosixPath(normalized).match(candidate) or PurePosixPath(name).match(
                    candidate
                ):
                    matched = True
                    break
            except ValueError:
                continue
        if matched:
            return True
        if any(char in cleaned for char in "*?["):
            continue
        prefix = cleaned.rstrip("/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def split_diff_by_file(
    diff: str, *, exclude_patterns: Sequence[str] = ()
) -> list[DiffFile]:
    """Split a unified git diff into per-file entries with line counts."""
    if not diff or not diff.strip():
        return []
    lines = diff.splitlines(keepends=True)
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") and current:
            chunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append(current)
    result: list[DiffFile] = []
    for chunk in chunks:
        header = chunk[0].rstrip("\n")
        if not header.startswith("diff --git "):
            continue
        label, path = _diff_file_paths(header, chunk)
        hunk = "".join(chunk).rstrip("\n")
        added, deleted = count_diff_lines(hunk)
        result.append(
            DiffFile(
                path=path,
                label=label,
                hunk=hunk,
                added=added,
                deleted=deleted,
                excluded=path_is_excluded(path, exclude_patterns),
            )
        )
    return result


def summarize_diff_files(files: Sequence[DiffFile]) -> Tuple[int, int, int, int]:
    """Return (added, deleted, added_excl, deleted_excl)."""
    added = deleted = added_excl = deleted_excl = 0
    for item in files:
        added += item.added
        deleted += item.deleted
        if not item.excluded:
            added_excl += item.added
            deleted_excl += item.deleted
    return added, deleted, added_excl, deleted_excl


def format_line_counts(added: int, deleted: int) -> str:
    return f"+{added} −{deleted}"


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_SKIP_DIFF_PREFIXES = (
    "diff --git ",
    "index ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "rename from ",
    "rename to ",
    "--- ",
    "+++ ",
    "Binary files ",
    "GIT binary ",
)


def format_unified_diff(
    hunk: str,
    *,
    line_markers: Optional[Mapping[Tuple[str, int], int]] = None,
    comments_by_anchor: Optional[Mapping[Tuple[str, int], Sequence[ReviewComment]]] = None,
) -> Text:
    """Render a file hunk as a unified diff with dual line-number gutters."""
    if not hunk or not hunk.strip():
        return Text("(empty diff)", style="dim")

    markers = line_markers or {}
    anchored = comments_by_anchor or {}
    range_lines = _range_line_marks(anchored)
    rows: list[Text] = []
    old_line = 0
    new_line = 0
    started = False

    def _append_marker(row: Text, side: str, number: int) -> None:
        count = markers.get((side, number), 0)
        if count:
            row.append(f"  ●{count}", style="bold yellow")
        elif (side, number) in range_lines:
            row.append("  ┃", style="yellow")

    def _flush_comments(side: str, number: int) -> None:
        comments = anchored.get((side, number))
        if not comments:
            return
        rows.extend(_inline_comment_rows(comments))

    for raw in hunk.splitlines():
        if raw.startswith(_SKIP_DIFF_PREFIXES):
            continue
        match = _HUNK_HEADER_RE.match(raw)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            started = True
            row = Text()
            row.append(f"{'':>4} {'':>4} │ ", style="dim")
            row.append(raw, style="bold cyan")
            rows.append(row)
            continue
        if not started and not raw.startswith((" ", "+", "-", "\\")):
            continue
        if raw.startswith("\\"):
            row = Text()
            row.append(f"{'':>4} {'':>4} │ ", style="dim")
            row.append(raw, style="dim italic")
            rows.append(row)
            continue
        if raw.startswith("+"):
            row = Text()
            row.append(f"{'':>4} ", style="dim")
            row.append(f"{new_line:>4} ", style="#81c995")
            row.append("│ ", style="dim")
            row.append(raw, style="#81c995 on #1b3329")
            _append_marker(row, "RIGHT", new_line)
            rows.append(row)
            _flush_comments("RIGHT", new_line)
            new_line += 1
            continue
        if raw.startswith("-"):
            row = Text()
            row.append(f"{old_line:>4} ", style="#f28b82")
            row.append(f"{'':>4} ", style="dim")
            row.append("│ ", style="dim")
            row.append(raw, style="#f28b82 on #3b2220")
            _append_marker(row, "LEFT", old_line)
            rows.append(row)
            _flush_comments("LEFT", old_line)
            old_line += 1
            continue
        display = raw if raw.startswith(" ") else f" {raw}"
        row = Text()
        row.append(f"{old_line:>4} ", style="dim")
        row.append(f"{new_line:>4} ", style="dim")
        row.append("│ ", style="dim")
        row.append(display, style="#e8eaed")
        _append_marker(row, "RIGHT", new_line)
        rows.append(row)
        _flush_comments("RIGHT", new_line)
        old_line += 1
        new_line += 1

    if not rows:
        return Text("(no hunks)", style="dim")

    result = Text()
    for offset, row in enumerate(rows):
        if offset:
            result.append("\n")
        result.append_text(row)
    return result


def review_comment_markers(
    comments: Sequence[ReviewComment], path: str
) -> dict[Tuple[str, int], int]:
    """Count comments whose end line is at each (side, line) — where bodies expand."""
    counts: dict[Tuple[str, int], int] = {}
    for comment in comments:
        if comment.path != path:
            continue
        line = comment.range_end
        if line is None:
            continue
        side = (comment.side or "RIGHT").upper()
        if side not in {"LEFT", "RIGHT"}:
            side = "RIGHT"
        key = (side, line)
        counts[key] = counts.get(key, 0) + 1
    return counts


def review_comments_by_anchor(
    comments: Sequence[ReviewComment], path: str
) -> dict[Tuple[str, int], tuple[ReviewComment, ...]]:
    """Map end-line anchors to comments (bodies render under the end line)."""
    grouped: dict[Tuple[str, int], list[ReviewComment]] = {}
    for comment in comments_for_path(comments, path):
        line = comment.range_end
        if line is None:
            continue
        side = (comment.side or "RIGHT").upper()
        if side not in {"LEFT", "RIGHT"}:
            side = "RIGHT"
        grouped.setdefault((side, line), []).append(comment)
    return {key: tuple(value) for key, value in grouped.items()}


def _range_line_marks(
    anchored: Mapping[Tuple[str, int], Sequence[ReviewComment]],
) -> set[Tuple[str, int]]:
    """Lines covered by a multi-line comment but not the end anchor."""
    marks: set[Tuple[str, int]] = set()
    for comments in anchored.values():
        for comment in comments:
            start = comment.range_start
            end = comment.range_end
            if start is None or end is None or start == end:
                continue
            side = (comment.side or "RIGHT").upper()
            if side not in {"LEFT", "RIGHT"}:
                side = "RIGHT"
            low, high = (start, end) if start <= end else (end, start)
            for number in range(low, high):
                marks.add((side, number))
    return marks


def comments_for_path(
    comments: Sequence[ReviewComment], path: str
) -> tuple[ReviewComment, ...]:
    return tuple(comment for comment in comments if comment.path == path)


def group_review_threads(
    comments: Sequence[ReviewComment],
) -> list[tuple[ReviewComment, ...]]:
    """Group comments into threads using ``in_reply_to_id``."""
    by_id = {comment.id: comment for comment in comments if comment.id}
    children: dict[int, list[ReviewComment]] = {}
    roots: list[ReviewComment] = []
    for comment in comments:
        parent = comment.in_reply_to_id
        if parent and parent in by_id:
            children.setdefault(parent, []).append(comment)
        else:
            roots.append(comment)
    threads: list[tuple[ReviewComment, ...]] = []
    for root in roots:
        thread = [root]
        queue = list(children.get(root.id, ()))
        while queue:
            reply = queue.pop(0)
            thread.append(reply)
            queue.extend(children.get(reply.id, ()))
        threads.append(tuple(thread))
    return threads


def _comment_location(comment: ReviewComment) -> str:
    where = comment.side or "RIGHT"
    start = comment.range_start
    end = comment.range_end
    if start is None and end is None:
        return where
    if start is None or end is None or start == end:
        return f"{where}:{end or start}"
    low, high = (start, end) if start <= end else (end, start)
    return f"{where}:{low}–{high}"


def format_review_comments(comments: Sequence[ReviewComment]) -> str:
    if not comments:
        return "No review comments on this file."
    blocks: list[str] = []
    for thread in group_review_threads(comments):
        for depth, comment in enumerate(thread):
            loc = _comment_location(comment)
            prefix = "#### " if depth else "### "
            who = comment.author or "unknown"
            heading = f"{prefix}{who}"
            if depth:
                heading += " (reply)"
            else:
                heading += f" · `{comment.path}` · {loc}"
            if comment.created_at:
                heading += f" · {comment.created_at}"
            indent = "  " * min(depth, 3)
            body = comment.body or "(empty)"
            body_lines = "\n".join(f"{indent}{part}" for part in body.splitlines()) or indent
            blocks.extend([heading, "", body_lines, ""])
        blocks.extend(["---", ""])
    while blocks and blocks[-1] in {"", "---"}:
        blocks.pop()
    return "\n".join(blocks).rstrip()


def _inline_comment_rows(comments: Sequence[ReviewComment]) -> list[Text]:
    rows: list[Text] = []
    for thread in group_review_threads(comments):
        for depth, comment in enumerate(thread):
            author = comment.author or "unknown"
            when = f" · {comment.created_at}" if comment.created_at else ""
            loc = _comment_location(comment)
            head = Text()
            head.append(f"{'':>4} {'':>4} │ ", style="dim")
            if depth == 0 and len(thread) == 1:
                branch = "● "
            elif depth == 0:
                branch = "┌ "
            elif depth == len(thread) - 1:
                branch = "└ "
            else:
                branch = "├ "
            head.append(branch, style="bold yellow")
            head.append(author, style="bold yellow")
            if depth:
                head.append(" (reply)", style="yellow")
            else:
                head.append(f" · {loc}", style="dim yellow")
            head.append(when, style="dim yellow")
            rows.append(head)
            body = (comment.body or "(empty)").splitlines() or ["(empty)"]
            for line in body:
                row = Text()
                row.append(f"{'':>4} {'':>4} │ ", style="dim")
                row.append("│ ", style="yellow")
                row.append(("  " * depth) + line, style="#fdd663 on #2b313b")
                rows.append(row)
        spacer = Text()
        spacer.append(f"{'':>4} {'':>4} │ ", style="dim")
        spacer.append("╰──", style="dim yellow")
        rows.append(spacer)
    return rows


def _diff_file_paths(header: str, chunk: Sequence[str]) -> Tuple[str, str]:
    parts = header[len("diff --git ") :].split()
    if len(parts) < 2:
        fallback = header[len("diff --git ") :].strip() or "(patch)"
        return fallback, fallback
    left = _strip_diff_prefix(parts[0])
    right = _strip_diff_prefix(parts[1])
    renamed = any(line.startswith("rename from ") for line in chunk[:8])
    if renamed and left != right:
        label = f"{left} → {right}"
        path = right if right and right != "/dev/null" else left
        return label, path
    if right and right != "/dev/null":
        return right, right
    if left and left != "/dev/null":
        return left, left
    path = right or left or "(patch)"
    return path, path


def _strip_diff_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class GithubPullsBackend:
    """Normalize read-only ``gh pr`` responses for the tasks TUI."""

    backend_label = "Pull requests"

    def __init__(
        self,
        repository: str,
        *,
        limit: int = 100,
        timeout: float = 45,
    ) -> None:
        if not isinstance(repository, str) or "/" not in repository:
            raise ValueError("repository must use owner/repo format")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("GitHub PR limit must be an integer from 1 to 1000")
        self.repository = repository.lower()
        self.limit = limit
        self.timeout = timeout
        self.scope_label = self.repository

    def list_pulls(
        self,
        search: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        include_closed: bool = False,
    ) -> Tuple[PullSummary, ...]:
        command = [
            "gh",
            "pr",
            "list",
            "--repo",
            self.repository,
            "--state",
            "all" if include_closed else "open",
            "--limit",
            str(self.limit),
            "--json",
            _LIST_FIELDS,
        ]
        query_parts: list[str] = []
        if search and search.strip():
            query_parts.append(search.strip())
        if assignee_filter is AssigneeFilter.ME:
            command.extend(["--assignee", "@me"])
        elif assignee_filter is AssigneeFilter.UNASSIGNED:
            query_parts.append("no:assignee")
        elif assignee_filter is AssigneeFilter.ASSIGNED_ANYONE:
            query_parts.append("has:assignee")
        elif assignee_filter is AssigneeFilter.ME_OR_UNASSIGNED:
            assigned = self.list_pulls(
                search, AssigneeFilter.ME, include_closed=include_closed
            )
            unassigned = self.list_pulls(
                search, AssigneeFilter.UNASSIGNED, include_closed=include_closed
            )
            merged: dict[str, PullSummary] = {}
            for item in assigned + unassigned:
                merged.setdefault(item.stable_id, item)
            return tuple(merged.values())[: self.limit]
        if query_parts:
            command.extend(["--search", " ".join(query_parts)])
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError as error:
            raise PullsError(
                f"Could not list pull requests for {self.repository}: {error}"
            ) from error
        if not isinstance(payload, list):
            raise PullsError("gh pr list returned invalid JSON")
        return tuple(_normalize_summary(item, self.repository) for item in payload)

    def get_pull(self, number: Union[int, str]) -> PullDetail:
        key = str(number).lstrip("#")
        command = [
            "gh",
            "pr",
            "view",
            key,
            "--repo",
            self.repository,
            "--json",
            _DETAIL_FIELDS,
        ]
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError as error:
            raise PullsError(
                f"Could not load pull request {self.repository}#{key}: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise PullsError("gh pr view returned invalid JSON")
        summary = _normalize_summary(payload, self.repository)
        checks = self.list_checks(summary.number)
        if checks:
            summary = PullSummary(
                repository=summary.repository,
                number=summary.number,
                title=summary.title,
                status=summary.status,
                author=summary.author,
                assignees=summary.assignees,
                labels=summary.labels,
                url=summary.url,
                is_draft=summary.is_draft,
                ci_state=_rollup_from_checks(checks),
                review_decision=summary.review_decision,
            )
        return PullDetail(
            summary=summary,
            description=_string(payload.get("body"), ""),
            comments=tuple(_normalize_comment(item) for item in _items(payload.get("comments"))),
            checks=checks,
            review_comments=self.list_review_comments(summary.number),
        )

    def list_review_comments(self, number: Union[int, str]) -> Tuple[ReviewComment, ...]:
        key = str(number).lstrip("#")
        command = [
            "gh",
            "api",
            f"repos/{self.repository}/pulls/{key}/comments",
            "--paginate",
        ]
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError:
            return ()
        if not isinstance(payload, list):
            return ()
        return tuple(
            _normalize_review_comment(item)
            for item in payload
            if isinstance(item, dict)
        )

    def list_checks(self, number: Union[int, str]) -> Tuple[CiCheck, ...]:
        key = str(number).lstrip("#")
        command = [
            "gh",
            "pr",
            "checks",
            key,
            "--repo",
            self.repository,
            "--json",
            "name,bucket,state,link",
        ]
        try:
            payload = run_json(command, timeout=self.timeout)
        except ProcessError as error:
            if error.kind is ProcessErrorKind.FAILED and error.returncode in {1, 8}:
                # gh exits non-zero when checks fail/pending but still emits JSON.
                payload = _parse_checks_fallback(error)
            else:
                return ()
        if not isinstance(payload, list):
            return ()
        return tuple(_normalize_check(item) for item in payload if isinstance(item, dict))

    def get_diff(self, number: Union[int, str]) -> str:
        key = str(number).lstrip("#")
        command = [
            "gh",
            "pr",
            "diff",
            key,
            "--repo",
            self.repository,
            "--color",
            "never",
        ]
        try:
            return run_text(command, timeout=max(self.timeout, 60))
        except ProcessError as error:
            raise PullsError(
                f"Could not load diff for {self.repository}#{key}: {error}"
            ) from error


def _parse_checks_fallback(error: ProcessError) -> list:
    # ProcessError does not carry stdout; treat as empty on hard failure.
    return []


def _normalize_summary(payload: Any, repository: str) -> PullSummary:
    item = _mapping(payload, "GitHub pull request")
    number = _positive_int(item.get("number"), "pull request number")
    author = item.get("author")
    if isinstance(author, dict):
        author_name = _string(author.get("login") or author.get("name"), "")
    else:
        author_name = _string(author, "")
    state = _string(item.get("state"), "OPEN").replace("_", " ").title()
    if item.get("isDraft") is True:
        state = f"Draft · {state}"
    rollup = item.get("statusCheckRollup")
    return PullSummary(
        repository=repository,
        number=number,
        title=_string(item.get("title"), "Untitled pull request"),
        status=state,
        author=author_name,
        assignees=_names(item.get("assignees")),
        labels=_names(item.get("labels")),
        url=_optional_string(item.get("url")),
        is_draft=bool(item.get("isDraft")),
        ci_state=_rollup_ci(rollup),
        review_decision=_optional_string(item.get("reviewDecision")),
    )


def _normalize_comment(payload: Any) -> Comment:
    item = _mapping(payload, "pull request comment")
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


def _normalize_review_comment(payload: Mapping[str, Any]) -> ReviewComment:
    user = payload.get("user")
    if isinstance(user, dict):
        author = _string(user.get("login") or user.get("name"), "unknown")
    else:
        author = "unknown"
    comment_id = payload.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int):
        comment_id = 0
    return ReviewComment(
        id=comment_id,
        path=_string(payload.get("path"), ""),
        body=_string(payload.get("body"), ""),
        author=author,
        side=_string(payload.get("side"), "RIGHT").upper() or "RIGHT",
        line=_optional_positive_int(payload.get("line")),
        start_line=_optional_positive_int(payload.get("start_line")),
        original_line=_optional_positive_int(payload.get("original_line")),
        original_start_line=_optional_positive_int(payload.get("original_start_line")),
        diff_hunk=_string(payload.get("diff_hunk"), ""),
        created_at=_optional_string(payload.get("created_at")),
        url=_optional_string(payload.get("html_url") or payload.get("url")),
        in_reply_to_id=_optional_positive_int(payload.get("in_reply_to_id")),
    )


def _optional_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _normalize_check(item: Mapping[str, Any]) -> CiCheck:
    bucket = _optional_string(item.get("bucket"))
    state = _ci_from_bucket(bucket) if bucket else _ci_from_text(item.get("state"))
    return CiCheck(
        name=_string(item.get("name"), "check"),
        state=state,
        bucket=bucket,
        link=_optional_string(item.get("link")),
    )


def _rollup_from_checks(checks: Sequence[CiCheck]) -> CiState:
    if not checks:
        return CiState.UNKNOWN
    states = {check.state for check in checks}
    for candidate in (
        CiState.FAIL,
        CiState.PENDING,
        CiState.CANCEL,
        CiState.SKIPPING,
        CiState.PASS,
    ):
        if candidate in states:
            return candidate
    return CiState.UNKNOWN


def _rollup_ci(value: Any) -> CiState:
    items = list(_items(value))
    if not items:
        return CiState.UNKNOWN
    states: list[CiState] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bucket = item.get("bucket")
        if isinstance(bucket, str) and bucket:
            states.append(_ci_from_bucket(bucket))
            continue
        conclusion = item.get("conclusion") or item.get("state")
        states.append(_ci_from_text(conclusion))
    if not states:
        return CiState.UNKNOWN
    unique = set(states)
    for candidate in (
        CiState.FAIL,
        CiState.PENDING,
        CiState.CANCEL,
        CiState.SKIPPING,
        CiState.PASS,
    ):
        if candidate in unique:
            return candidate
    return CiState.UNKNOWN


def _ci_from_bucket(bucket: str) -> CiState:
    normalized = bucket.casefold().strip()
    mapping = {
        "pass": CiState.PASS,
        "fail": CiState.FAIL,
        "pending": CiState.PENDING,
        "skipping": CiState.SKIPPING,
        "cancel": CiState.CANCEL,
    }
    return mapping.get(normalized, CiState.UNKNOWN)


def _ci_from_text(value: Any) -> CiState:
    if not isinstance(value, str) or not value.strip():
        return CiState.UNKNOWN
    normalized = value.casefold().replace("_", " ").strip()
    if normalized in {"success", "pass", "passed", "completed success"}:
        return CiState.PASS
    if normalized in {"failure", "fail", "failed", "error", "action required"}:
        return CiState.FAIL
    if normalized in {"pending", "queued", "in progress", "expected", "running"}:
        return CiState.PENDING
    if normalized in {"skipped", "skipping", "neutral"}:
        return CiState.SKIPPING
    if normalized in {"cancelled", "canceled", "cancel"}:
        return CiState.CANCEL
    return CiState.UNKNOWN


def _items(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("nodes"), list):
        return value["nodes"]
    return (value,)


def _names(value: Any) -> Tuple[str, ...]:
    names: List[str] = []
    for item in _items(value):
        if isinstance(item, dict):
            name = item.get("login") or item.get("name")
        else:
            name = item
        if isinstance(name, str) and name:
            names.append(name)
    return tuple(names)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PullsError(f"{name} data is invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PullsError(f"{name} is invalid")
    return value


def _string(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None
