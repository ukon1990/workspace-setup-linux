"""Pull-request list helpers and session controller for the tasks TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..filters import AssigneeFilter
from ..models import CiState, PullDetail, PullSummary
from ..pulls import GithubPullsBackend, ci_state_rank


@dataclass
class PullListState:
    pulls: list[PullSummary] = field(default_factory=list)
    query: Optional[str] = None
    assignee_filter: AssigneeFilter = AssigneeFilter.ALL
    filter_text: str = ""
    index: int = 0
    error: Optional[str] = None
    sort_column: Optional[str] = None
    sort_reverse: bool = False
    repo_error: Optional[str] = None


PULL_SORT_COLUMNS = ("key", "ci", "status", "author", "title")


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


def _pull_sort_value(pull: PullSummary, column: str):
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
    return pull.stable_id


def sort_pulls(
    pulls: Sequence[PullSummary],
    column: Optional[str] = None,
    reverse: bool = False,
) -> list[PullSummary]:
    items = list(pulls)
    if not column or column not in PULL_SORT_COLUMNS:
        return items
    return sorted(
        items,
        key=lambda pull: (_pull_sort_value(pull, column), pull.stable_id),
        reverse=reverse,
    )


def visible_pulls(state: PullListState) -> list[PullSummary]:
    return sort_pulls(
        filter_pulls(state.pulls, state.filter_text),
        state.sort_column,
        state.sort_reverse,
    )


def selected_pull(state: PullListState) -> Optional[PullSummary]:
    pulls = visible_pulls(state)
    if not pulls:
        return None
    state.index = min(max(state.index, 0), len(pulls) - 1)
    return pulls[state.index]


def set_pull_filter(state: PullListState, value: str) -> None:
    state.filter_text = value
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


def pull_detail_markdown(detail: PullDetail, *, checks_text: Optional[str] = None) -> str:
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
            heading = f"### {comment.author}"
            if comment.created_at:
                heading += f" · {comment.created_at}"
            lines.extend(("", heading, "", comment.body or "(empty comment)"))
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


class PullsController:
    """Load and cache pull-request lists/details."""

    def __init__(
        self,
        backend: Optional[GithubPullsBackend],
        *,
        exclude_patterns: Sequence[str] = (),
    ) -> None:
        self.backend = backend
        self.exclude_patterns = tuple(exclude_patterns)
        self.detail_cache: dict[str, PullDetail] = {}
        self.diff_cache: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return self.backend is not None

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
            state.pulls = list(
                self.backend.list_pulls(
                    state.query,
                    state.assignee_filter,
                    include_closed=bool(state.query) or full,
                )
            )
            count = len(filter_pulls(state.pulls, state.filter_text))
            state.index = min(max(state.index, 0), max(0, count - 1))
        except Exception as error:
            state.error = str(error) or type(error).__name__

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
