"""Pure helpers and backend session logic for the tasks TUI."""

from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from ..filters import AssigneeFilter, WorkFilter
from ..models import (
    BackendIdentity,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)
from ..readiness import Readiness, evaluate, is_done, is_done_status  # noqa: F401
from ..references import github_identity, jira_identity

DEFAULT_TREE_MAX_DEPTH = 8
DEFAULT_TREE_MAX_NODES = 80
DEFAULT_DETAIL_ANCESTORS = 8
DEFAULT_DETAIL_DESCENDANT_DEPTH = 2


@dataclass(frozen=True)
class SyncProgress:
    """One sync phase update for the status bar."""

    done: int
    total: int
    label: str
    eta_seconds: Optional[float] = None


def eta_from_durations(
    completed: Sequence[float], remaining: int
) -> Optional[float]:
    """Estimate remaining seconds from the mean of finished phase durations."""
    if not completed or remaining <= 0:
        return None
    return (sum(completed) / len(completed)) * remaining


def format_sync_progress(progress: SyncProgress) -> str:
    if not progress.total:
        return progress.label
    current = min(progress.done + 1, progress.total) if progress.total else 0
    if progress.done >= progress.total and progress.total:
        current = progress.total
    parts = [f"Syncing {current}/{progress.total}", progress.label]
    if progress.eta_seconds is not None:
        parts.append(f"ETA ~{max(1, int(round(progress.eta_seconds)))}s")
    return " · ".join(parts)


class PhaseRunner:
    """Run named sync steps, reporting progress and timing for ETA."""

    def __init__(
        self,
        labels: Sequence[str],
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
    ) -> None:
        self.labels = list(labels)
        self.total = len(self.labels)
        self.on_progress = on_progress
        self.durations: list[float] = []
        self.done = 0

    def run(self, label: str, action: Callable[[], Any]) -> Any:
        self._emit(label)
        started = time.monotonic()
        result = action()
        self.durations.append(time.monotonic() - started)
        self.done += 1
        return result

    def _emit(self, label: str) -> None:
        if self.on_progress is None:
            return
        remaining = max(self.total - self.done, 0)
        self.on_progress(
            SyncProgress(
                done=self.done,
                total=self.total,
                label=label,
                eta_seconds=eta_from_durations(self.durations, remaining),
            )
        )


class TaskBackend(Protocol):
    """Small interface implemented by Jira and GitHub integrations."""

    backend_label: str
    scope_label: str

    def list_tasks(
        self,
        query: Optional[str] = None,
        refresh: bool = False,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        updated_since: Optional[str] = None,
        include_closed: bool = False,
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
    sort_column: Optional[str] = None
    sort_reverse: bool = False
    work_filter: WorkFilter = WorkFilter.ALL
    readiness: Readiness = field(default_factory=Readiness)
    changed_ids: set[str] = field(default_factory=set)


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


TABLE_SORT_COLUMNS = (
    "key",
    "status",
    "type",
    "priority",
    "assignees",
    "title",
    "blocked_by",
    "blocks",
    "work",
    "ready_descendants",
    "changed",
)


def _sort_value(task: TaskSummary, column: str):
    if column == "key":
        return task.display_key.casefold()
    if column == "status":
        return task.status.casefold()
    if column == "type":
        return (task.task_type or "").casefold()
    if column == "priority":
        return (task.priority or "").casefold()
    if column == "assignees":
        return ", ".join(task.assignees).casefold()
    if column == "title":
        return task.title.casefold()
    if column == "blocked_by":
        return len(task.blocked_by)
    if column == "blocks":
        return len(task.blocks)
    return task.identity.stable_id


def sort_tasks(
    tasks: Sequence[TaskSummary],
    column: Optional[str] = None,
    reverse: bool = False,
) -> list[TaskSummary]:
    """Order tasks for the overview table; unknown/None column keeps input order."""
    items = list(tasks)
    if not column or column not in TABLE_SORT_COLUMNS:
        return items
    return sorted(
        items,
        key=lambda task: (_sort_value(task, column), task.identity.stable_id),
        reverse=reverse,
    )


def work_result(state: ListState) -> Readiness:
    cache_key = (id(state.readiness), tuple(state.tasks), state.filter_text)
    if getattr(state, "_work_cache_key", None) == cache_key:
        return state._work_cache
    items = {task.identity.stable_id: task for task in state.tasks}
    items.update(state.readiness.items)
    result = evaluate(items, filter_tasks(state.tasks, state.filter_text), partial=state.readiness.partial)
    state._work_cache_key = cache_key
    state._work_cache = result
    return result


def visible_tasks(state: ListState) -> list[TaskSummary]:
    """One selection pipeline for table rows, navigation and work filtering."""
    result = work_result(state)
    tasks = result.selected(state.work_filter.value)
    if state.sort_column == "changed":
        return sorted(tasks, key=lambda task: (task.identity.stable_id in state.changed_ids, task.identity.stable_id), reverse=state.sort_reverse)
    if state.sort_column in {"work", "ready_descendants"}:
        values = result.states if state.sort_column == "work" else result.ready_descendants
        return sorted(tasks, key=lambda task: (values[task.identity.stable_id], task.identity.stable_id),
                      reverse=state.sort_reverse)
    return sort_tasks(tasks, state.sort_column, state.sort_reverse)


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


def resolve_goto_identity(
    backend: TaskBackend, value: str
) -> Optional[BackendIdentity]:
    """Parse a direct issue/task ID for the active backend, or None if invalid."""
    stripped = value.strip()
    if not stripped:
        return None
    label = getattr(backend, "backend_label", "").casefold()
    if label == "jira":
        return jira_identity(stripped)
    default_repo = getattr(backend, "repository", None) or getattr(
        backend, "scope_label", None
    )
    if isinstance(default_repo, str) and not default_repo.strip():
        default_repo = None
    return github_identity(stripped, default_repo=default_repo)


def selected_task(state: ListState) -> Optional[TaskSummary]:
    tasks = visible_tasks(state)
    if not tasks:
        return None
    state.index = min(max(state.index, 0), len(tasks) - 1)
    return tasks[state.index]


def detail_content_lines(detail: TaskDetail) -> list[str]:
    """Build a Markdown document for the detail pane (bodies left unwrapped)."""
    summary = detail.summary
    metadata = [
        f"**Status:** {summary.status}",
        f"**Type:** {summary.task_type or '-'}  **Priority:** {summary.priority or '-'}",
        f"**Assignees:** {', '.join(summary.assignees) or '-'}",
        f"**Labels:** {', '.join(summary.labels) or '-'}",
        f"**Components:** {', '.join(summary.components) or '-'}",
    ]
    lines = metadata + ["", "## Description", "", detail.description or "(no description)"]
    if detail.comments:
        lines.extend(("", "## Comments"))
        for comment in detail.comments:
            heading = f"### {comment.author}"
            if comment.created_at:
                heading += f" · {comment.created_at}"
            lines.extend(("", heading, "", comment.body or "(empty comment)"))
    return lines


def detail_content_text(detail: TaskDetail) -> str:
    """Full detail body as Markdown for the scrollable detail pane."""
    return "\n".join(detail_content_lines(detail))


def relationship_line(relationship: TaskRelationship) -> str:
    suffix = f" — {relationship.summary}" if relationship.summary else ""
    return f"{relationship.label}: {relationship.target.display_key}{suffix}"


def blocked_by_label(task: TaskSummary) -> str:
    count = len(task.blocked_by)
    return f"blocked by {count}" if count else "-"


def blocks_label(task: TaskSummary) -> str:
    count = len(task.blocks)
    return f"blocks {count}" if count else "-"


def dependency_suffix(
    blocked_by: Sequence[BackendIdentity] = (),
    blocks: Sequence[BackendIdentity] = (),
) -> str:
    """Compact tree annotation for blockers / blocking targets."""
    parts: list[str] = []
    if blocked_by:
        parts.append(f"blocked by {len(blocked_by)}")
    if blocks:
        parts.append(f"blocks {len(blocks)}")
    return (" " + " · ".join(parts)) if parts else ""


def task_url(
    detail: Optional[TaskDetail], identity: Optional[BackendIdentity] = None
) -> Optional[str]:
    if detail is not None:
        return detail.summary.url or detail.identity.url
    if identity is not None:
        return identity.url
    return None


def presentation_tasks(
    items: Mapping[str, TaskSummary], query: Optional[str]
) -> list[TaskSummary]:
    """Default open list hides done issues; searches keep the full cached set."""
    tasks = list(items.values())
    if query:
        return tasks
    return [task for task in tasks if not is_done(task)]


def merge_task_summaries(
    *groups: Sequence[TaskSummary], limit: Optional[int] = None
) -> list[TaskSummary]:
    """Deduplicate summaries by stable_id, preserving first-seen order."""
    merged: dict[str, TaskSummary] = {}
    for group in groups:
        for task in group:
            merged.setdefault(task.identity.stable_id, task)
    items = list(merged.values())
    if limit is not None:
        return items[:limit]
    return items


def _backend_limit(backend: TaskBackend) -> Optional[int]:
    for attr in ("limit",):
        value = getattr(backend, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    nested = getattr(backend, "backend", None)
    value = getattr(nested, "limit", None) if nested is not None else None
    if isinstance(value, int) and value > 0:
        return value
    return None



# Keep the public helper API while implementations live in focused modules.
from .controller import TasksController  # noqa: E402, F401
from .hierarchy import (  # noqa: E402, F401
    HierarchyNode,
    build_forest_from_details,
    build_forest_from_summaries,
    build_relationship_hierarchy,
    compute_progress,
    expand_hierarchy,
)
