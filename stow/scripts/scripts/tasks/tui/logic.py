"""Pure helpers and backend session logic for the tasks TUI."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, Sequence

from ..filters import AssigneeFilter
from ..models import BackendIdentity, TaskDetail, TaskRelationship, TaskSummary


class TaskBackend(Protocol):
    """Small interface implemented by Jira and GitHub integrations."""

    backend_label: str
    scope_label: str

    def list_tasks(
        self,
        query: Optional[str] = None,
        refresh: bool = False,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    ) -> Sequence[TaskSummary]: ...

    def get_task(self, identity: BackendIdentity, refresh: bool = False) -> TaskDetail: ...


@dataclass
class ListState:
    tasks: list[TaskSummary] = field(default_factory=list)
    query: Optional[str] = None
    assignee_filter: AssigneeFilter = AssigneeFilter.ALL
    filter_text: str = ""
    index: int = 0
    error: Optional[str] = None


def clip(text: str, width: int) -> str:
    """Clip text to a terminal row without producing negative slices."""
    return text[: max(0, width)]


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap arbitrary task text while preserving blank lines."""
    if width <= 0:
        return []
    lines: list[str] = []
    for source_line in (text or "").splitlines() or [""]:
        if not source_line:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                source_line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def filter_tasks(tasks: Sequence[TaskSummary], value: str) -> list[TaskSummary]:
    needle = value.casefold().strip()
    if not needle:
        return list(tasks)
    return [
        task
        for task in tasks
        if needle
        in " ".join(
            (
                task.display_key,
                task.title,
                task.status,
                task.task_type or "",
                task.priority or "",
                *task.assignees,
                *task.labels,
                *task.components,
            )
        ).casefold()
    ]


def assignee_filter_text(value: AssigneeFilter) -> str:
    return {
        AssigneeFilter.ALL: "all",
        AssigneeFilter.ME: "@me",
        AssigneeFilter.UNASSIGNED: "unassigned",
        AssigneeFilter.ME_OR_UNASSIGNED: "@me-or-unassigned",
        AssigneeFilter.ASSIGNED_ANYONE: "assigned",
    }[value]


def assignee_filter_for_key(key: object) -> Optional[AssigneeFilter]:
    if isinstance(key, str):
        return {
            "a": AssigneeFilter.ALL,
            "m": AssigneeFilter.ME,
            "u": AssigneeFilter.UNASSIGNED,
            "o": AssigneeFilter.ME_OR_UNASSIGNED,
            "d": AssigneeFilter.ASSIGNED_ANYONE,
        }.get(key.casefold())
    return None


ASSIGNEE_FILTER_OPTIONS: tuple[tuple[AssigneeFilter, str, str], ...] = (
    (AssigneeFilter.ALL, "a", "All"),
    (AssigneeFilter.ME, "m", "Assigned to me (@me)"),
    (AssigneeFilter.UNASSIGNED, "u", "Unassigned"),
    (AssigneeFilter.ME_OR_UNASSIGNED, "o", "Me or unassigned"),
    (AssigneeFilter.ASSIGNED_ANYONE, "d", "Assigned to anyone"),
)


def set_filter(state: ListState, value: str) -> None:
    state.filter_text = value
    state.index = 0


def selected_task(state: ListState) -> Optional[TaskSummary]:
    tasks = filter_tasks(state.tasks, state.filter_text)
    if not tasks:
        return None
    state.index = min(max(state.index, 0), len(tasks) - 1)
    return tasks[state.index]


def detail_content_lines(detail: TaskDetail, width: int) -> list[str]:
    summary = detail.summary
    metadata = [
        f"Status: {summary.status}",
        f"Type: {summary.task_type or '-'}  Priority: {summary.priority or '-'}",
        f"Assignees: {', '.join(summary.assignees) or '-'}",
        f"Labels: {', '.join(summary.labels) or '-'}",
        f"Components: {', '.join(summary.components) or '-'}",
    ]
    lines = metadata + ["", "Description"]
    lines.extend(wrap_text(detail.description or "(no description)", width))
    if detail.comments:
        lines.extend(("", "Comments"))
        for comment in detail.comments:
            heading = comment.author
            if comment.created_at:
                heading += f" · {comment.created_at}"
            lines.extend((heading, *wrap_text(comment.body or "(empty comment)", width), ""))
    return lines


def detail_content_text(detail: TaskDetail) -> str:
    """Full detail body for a scrollable pane (no fixed wrap width)."""
    return "\n".join(detail_content_lines(detail, width=100))


def relationship_line(relationship: TaskRelationship) -> str:
    suffix = f" — {relationship.summary}" if relationship.summary else ""
    return f"{relationship.label}: {relationship.target.display_key}{suffix}"


def task_url(
    detail: Optional[TaskDetail], identity: Optional[BackendIdentity] = None
) -> Optional[str]:
    if detail is not None:
        return detail.summary.url or detail.identity.url
    if identity is not None:
        return identity.url
    return None


class TasksController:
    """Backend session + list/detail loading shared by screens and tests."""

    def __init__(
        self,
        backend: TaskBackend,
        *,
        initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
    ) -> None:
        self.backend = backend
        self._initial_assignee_filter = initial_assignee_filter
        self._on_assignee_filter_change = on_assignee_filter_change
        self.detail_cache: dict[str, TaskDetail] = {}

    def load_list(self, state: ListState, *, refresh: bool = False) -> None:
        state.error = None
        try:
            state.tasks = list(
                self.backend.list_tasks(
                    query=state.query,
                    refresh=refresh,
                    assignee_filter=state.assignee_filter,
                )
            )
            count = len(filter_tasks(state.tasks, state.filter_text))
            state.index = min(max(state.index, 0), max(0, count - 1))
        except Exception as error:  # Backends expose user-ready errors.
            state.error = str(error) or type(error).__name__

    def load_detail(
        self,
        identity: BackendIdentity,
        *,
        refresh: bool = False,
    ) -> tuple[Optional[TaskDetail], Optional[str]]:
        stable_id = identity.stable_id
        if not refresh and stable_id in self.detail_cache:
            return self.detail_cache[stable_id], None
        try:
            detail = self.backend.get_task(identity, refresh=refresh)
        except Exception as error:  # A failed relationship must remain selectable.
            return None, str(error) or type(error).__name__
        self.detail_cache[stable_id] = detail
        return detail, None

    def change_assignee_filter(
        self,
        state: ListState,
        selection: AssigneeFilter,
        *,
        notify_if_unchanged: bool = False,
        reload_if_unchanged: bool = False,
    ) -> bool:
        changed = state.assignee_filter is not selection
        if changed:
            state.assignee_filter = selection
            state.index = 0
        if changed or reload_if_unchanged:
            self.load_list(state)
        if (changed or notify_if_unchanged) and self._on_assignee_filter_change:
            try:
                self._on_assignee_filter_change(selection)
            except Exception as error:
                message = str(error) or type(error).__name__
                state.error = f"{state.error}; {message}" if state.error else message
        return changed

    def clear_filters(self, state: ListState) -> bool:
        set_filter(state, "")
        return self.change_assignee_filter(
            state,
            AssigneeFilter.ALL,
            notify_if_unchanged=True,
        )

    def make_list_state(
        self,
        *,
        tasks: Optional[Sequence[TaskSummary]] = None,
        query: Optional[str] = None,
        assignee_filter: Optional[AssigneeFilter] = None,
    ) -> ListState:
        return ListState(
            list(tasks or ()),
            query=query,
            assignee_filter=(
                assignee_filter if assignee_filter is not None else self._initial_assignee_filter
            ),
        )
