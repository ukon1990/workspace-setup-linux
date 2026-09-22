"""Pull-request list helpers and session controller for the tasks TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from ..cache import (
    PullCacheEntry,
    format_github_since,
    load_pull_entry,
    save_pull_entry,
    utc_now_iso,
)
from ..filters import AssigneeFilter
from ..models import CiState, Comment, PullDetail, PullSummary
from ..pr_views import activity_label, load_pr_viewed_at, mark_pr_viewed
from ..pulls import GithubPullsBackend, ci_state_rank, is_newer_than


@dataclass
class PullListState:
    pulls: list[PullSummary] = field(default_factory=list)
    query: Optional[str] = None
    assignee_filter: AssigneeFilter = AssigneeFilter.ALL
    filter_text: str = ""
    author_filter: frozenset[str] = field(default_factory=frozenset)
    index: int = 0
    error: Optional[str] = None
    sort_column: Optional[str] = "updated"
    sort_reverse: bool = True
    repo_error: Optional[str] = None


PULL_SORT_COLUMNS = ("key", "ci", "status", "author", "title", "updated", "created", "activity")


def filter_pulls(pulls: Sequence[PullSummary], value: str) -> list[PullSummary]:
    needle = value.casefold().strip()
    if not needle:
        return list(pulls)
    return [
        pull
        for pull in pulls
        if needle
        in " ".join(
            (
                pull.display_key,
                pull.title,
                pull.status,
                pull.author,
                pull.ci_state.value,
                *pull.assignees,
                *pull.labels,
            )
        ).casefold()
    ]


def filter_pulls_by_authors(
    pulls: Sequence[PullSummary], authors: frozenset[str]
) -> list[PullSummary]:
    if not authors:
        return list(pulls)
    return [pull for pull in pulls if pull.author in authors]


def authors_from_pulls(pulls: Sequence[PullSummary]) -> list[str]:
    seen: set[str] = set()
    authors: list[str] = []
    for pull in pulls:
        name = pull.author.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        authors.append(name)
    authors.sort(key=str.casefold)
    return authors


def format_pull_timestamp(value: Optional[str]) -> str:
    if not value:
        return "-"
    stamp = value.strip()
    if "T" in stamp:
        date, _, rest = stamp.partition("T")
        time = rest[:5] if len(rest) >= 5 else rest.rstrip("Z")
        return f"{date} {time}" if time else date
    return stamp[:16] or "-"


def is_pull_closed(pull: PullSummary) -> bool:
    status = pull.status.casefold()
    return "closed" in status or "merged" in status


def presentation_pulls(
    items: Mapping[str, PullSummary], query: Optional[str]
) -> list[PullSummary]:
    pulls = list(items.values())
    if query:
        return pulls
    return [pull for pull in pulls if not is_pull_closed(pull)]


def _pull_sort_value(pull: PullSummary, column: str, viewed_at: Optional[str] = None):
    if column == "key":
        return (pull.repository.casefold(), pull.number)
    if column == "ci":
        return ci_state_rank(pull.ci_state)
    if column == "status":
        return pull.status.casefold()
    if column == "author":
        return pull.author.casefold()
    if column == "title":
        return pull.title.casefold()
    if column == "updated":
        return pull.updated_at or ""
    if column == "created":
        return pull.created_at or ""
    if column == "activity":
        return activity_label(pull.updated_at, viewed_at)
    return pull.stable_id


def sort_pulls(
    pulls: Sequence[PullSummary],
    column: Optional[str] = None,
    reverse: bool = False,
    *,
    viewed_times: Optional[Mapping[str, Optional[str]]] = None,
) -> list[PullSummary]:
    items = list(pulls)
    if not column or column not in PULL_SORT_COLUMNS:
        return items
    views = viewed_times or {}
    return sorted(
        items,
        key=lambda pull: (
            _pull_sort_value(pull, column, views.get(pull.stable_id)),
            pull.stable_id,
        ),
        reverse=reverse,
    )


def visible_pulls(
    state: PullListState,
    *,
    viewed_times: Optional[Mapping[str, Optional[str]]] = None,
) -> list[PullSummary]:
    filtered = filter_pulls(state.pulls, state.filter_text)
    filtered = filter_pulls_by_authors(filtered, state.author_filter)
    return sort_pulls(
        filtered,
        state.sort_column,
        state.sort_reverse,
        viewed_times=viewed_times,
    )


def selected_pull(
    state: PullListState,
    *,
    viewed_times: Optional[Mapping[str, Optional[str]]] = None,
) -> Optional[PullSummary]:
    pulls = visible_pulls(state, viewed_times=viewed_times)
    if not pulls:
        return None
    state.index = min(max(state.index, 0), len(pulls) - 1)
    return pulls[state.index]


def set_pull_filter(state: PullListState, value: str) -> None:
    state.filter_text = value
    state.index = 0


def set_author_filter(state: PullListState, authors: frozenset[str]) -> None:
    state.author_filter = authors
    state.index = 0


def ci_label(state: CiState) -> str:
    return {
        CiState.PASS: "pass",
        CiState.FAIL: "fail",
        CiState.PENDING: "pending",
        CiState.SKIPPING: "skip",
        CiState.CANCEL: "cancel",
        CiState.UNKNOWN: "-",
    }[state]


def pull_detail_markdown(
    detail: PullDetail,
    *,
    checks_text: Optional[str] = None,
    viewed_at: Optional[str] = None,
) -> str:
    summary = detail.summary
    lines = [
        f"**State:** {summary.status}",
        f"**Author:** {summary.author or '-'}",
        f"**Assignees:** {', '.join(summary.assignees) or '-'}",
        f"**CI:** {ci_label(summary.ci_state)}",
        f"**Review:** {summary.review_decision or '-'}",
        "",
        "## Description",
        "",
        detail.description or "(no description)",
    ]
    if detail.comments:
        lines.extend(("", "## Comments"))
        for comment in detail.comments:
            lines.extend(("", _comment_heading(comment, viewed_at), "", comment.body or "(empty comment)"))
    ci_block = checks_text
    if ci_block is None:
        if detail.checks:
            ci_block = "\n".join(
                f"- `{ci_label(check.state)}` {check.name}"
                + (f" — {check.link}" if check.link else "")
                for check in detail.checks
            )
        else:
            ci_block = "No CI checks."
    lines.extend(("", "## CI", "", ci_block))
    return "\n".join(lines)


def _comment_heading(comment: Comment, viewed_at: Optional[str]) -> str:
    heading = f"### {comment.author}"
    if comment.created_at:
        heading += f" · {comment.created_at}"
    if is_newer_than(comment.created_at, viewed_at):
        heading += " (new)"
    return heading


class PullsController:
    """Load and cache pull-request lists/details."""

    def __init__(
        self,
        backend: Optional[GithubPullsBackend],
        *,
        exclude_patterns: Sequence[str] = (),
        cache_scope: Optional[str] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        views_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.backend = backend
        self.exclude_patterns = tuple(exclude_patterns)
        self.cache_scope = cache_scope
        self.cache_dir = cache_dir
        self.views_path = views_path
        self.detail_cache: dict[str, PullDetail] = {}
        self.diff_cache: dict[str, str] = {}
        self.cached_items: dict[str, PullSummary] = {}
        self._synced_at: Optional[str] = None
        self._viewed_times: dict[str, Optional[str]] = {}

    @property
    def available(self) -> bool:
        return self.backend is not None

    def viewed_at(self, pull_stable_id: str) -> Optional[str]:
        if pull_stable_id not in self._viewed_times:
            self._viewed_times[pull_stable_id] = load_pr_viewed_at(
                pull_stable_id, path=self.views_path
            )
        return self._viewed_times[pull_stable_id]

    def viewed_times_for(self, pulls: Sequence[PullSummary]) -> dict[str, Optional[str]]:
        return {pull.stable_id: self.viewed_at(pull.stable_id) for pull in pulls}

    def mark_viewed(self, pull_stable_id: str) -> str:
        stamp = mark_pr_viewed(pull_stable_id, path=self.views_path)
        self._viewed_times[pull_stable_id] = stamp
        return stamp

    def make_list_state(
        self,
        *,
        query: Optional[str] = None,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        repo_error: Optional[str] = None,
    ) -> PullListState:
        return PullListState(
            query=query,
            assignee_filter=assignee_filter,
            repo_error=repo_error,
        )

    def load_list(
        self,
        state: PullListState,
        *,
        refresh: bool = False,
        full: bool = False,
    ) -> None:
        state.error = None
        if state.repo_error:
            state.pulls = []
            state.error = state.repo_error
            return
        if self.backend is None:
            state.pulls = []
            state.error = "No GitHub repository resolved for pull requests."
            return
        try:
            if self.cache_scope:
                self._load_list_cached(state, refresh=refresh, full=full)
            else:
                state.pulls = list(
                    self.backend.list_pulls(
                        state.query,
                        state.assignee_filter,
                        include_closed=bool(state.query) or full,
                    )
                )
                self.cached_items = {pull.stable_id: pull for pull in state.pulls}
            count = len(filter_pulls(state.pulls, state.filter_text))
            state.index = min(max(state.index, 0), max(0, count - 1))
        except Exception as error:
            state.error = str(error) or type(error).__name__

    def _load_list_cached(
        self,
        state: PullListState,
        *,
        refresh: bool,
        full: bool,
    ) -> None:
        assert self.cache_scope is not None
        entry = load_pull_entry(
            self.cache_scope,
            state.query,
            state.assignee_filter,
            cache_dir=self.cache_dir,
        )
        if entry is not None and not refresh and not full:
            self.cached_items = dict(entry.items)
            self._synced_at = entry.synced_at
            state.pulls = presentation_pulls(self.cached_items, state.query)
            return

        if entry is not None and refresh and not full:
            since = format_github_since(entry.synced_at)
            delta = list(
                self.backend.list_pulls(
                    state.query,
                    state.assignee_filter,
                    include_closed=True,
                    updated_since=since,
                )
            )
            entry.merge_items(delta)
            entry.synced_at = utc_now_iso()
            save_pull_entry(self.cache_scope, entry, cache_dir=self.cache_dir)
            self.cached_items = dict(entry.items)
            self._synced_at = entry.synced_at
            state.pulls = presentation_pulls(self.cached_items, state.query)
            return

        fetched = list(
            self.backend.list_pulls(
                state.query,
                state.assignee_filter,
                include_closed=bool(state.query),
            )
        )
        new_entry = PullCacheEntry(
            synced_at=utc_now_iso(),
            query=state.query,
            assignee=state.assignee_filter,
        )
        new_entry.replace_items(fetched)
        save_pull_entry(self.cache_scope, new_entry, cache_dir=self.cache_dir)
        self.cached_items = dict(new_entry.items)
        self._synced_at = new_entry.synced_at
        state.pulls = presentation_pulls(self.cached_items, state.query)

    def load_detail(
        self, pull: PullSummary, *, refresh: bool = False
    ) -> tuple[Optional[PullDetail], Optional[str]]:
        if self.backend is None:
            return None, "No GitHub repository resolved for pull requests."
        if not refresh and pull.stable_id in self.detail_cache:
            return self.detail_cache[pull.stable_id], None
        try:
            detail = self.backend.get_pull(pull.number)
        except Exception as error:
            return None, str(error) or type(error).__name__
        self.detail_cache[pull.stable_id] = detail
        return detail, None

    def load_diff(self, pull: PullSummary, *, refresh: bool = False) -> tuple[str, Optional[str]]:
        if self.backend is None:
            return "", "No GitHub repository resolved for pull requests."
        if not refresh and pull.stable_id in self.diff_cache:
            return self.diff_cache[pull.stable_id], None
        try:
            diff = self.backend.get_diff(pull.number)
        except Exception as error:
            return "", str(error) or type(error).__name__
        self.diff_cache[pull.stable_id] = diff
        return diff, None

    def submit_review(
        self,
        pull: PullSummary,
        event: str,
        *,
        body: str = "",
        comments: Sequence[dict] = (),
    ) -> Optional[str]:
        """Submit a review; returns an error string or None on success."""
        if self.backend is None:
            return "No GitHub repository resolved for pull requests."
        try:
            self.backend.submit_review(
                pull.number, event, body=body, comments=comments
            )
        except Exception as error:
            return str(error) or type(error).__name__
        self.detail_cache.pop(pull.stable_id, None)
        return None

    def change_assignee_filter(
        self,
        state: PullListState,
        selection: AssigneeFilter,
        *,
        reload_if_unchanged: bool = False,
    ) -> bool:
        changed = state.assignee_filter is not selection
        if changed:
            state.assignee_filter = selection
            state.index = 0
        if changed or reload_if_unchanged:
            self.load_list(state, refresh=True)
        return changed
