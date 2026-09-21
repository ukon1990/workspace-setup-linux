"""Pure helpers and backend session logic for the tasks TUI."""

from __future__ import annotations

import textwrap
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from ..cache import (
    CacheEntry,
    format_github_since,
    format_jira_since,
    load_entry,
    save_entry,
    utc_now_iso,
)
from ..filters import AssigneeFilter
from ..models import (
    BackendIdentity,
    RelationshipKind,
    TaskDetail,
    TaskRelationship,
    TaskSummary,
)

_DONE_STATUSES = frozenset(
    {
        "closed",
        "completed",
        "not planned",
        "done",
        "resolved",
        "cancelled",
        "canceled",
    }
)

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


def visible_tasks(state: ListState) -> list[TaskSummary]:
    """Filtered overview rows in the active table sort order."""
    return sort_tasks(
        filter_tasks(state.tasks, state.filter_text),
        state.sort_column,
        state.sort_reverse,
    )


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


def is_done_status(status: str) -> bool:
    normalized = status.casefold().replace("_", " ").strip()
    return normalized in _DONE_STATUSES


def is_done(summary: TaskSummary) -> bool:
    return is_done_status(summary.status)


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


@dataclass
class HierarchyNode:
    identity: BackendIdentity
    title: str
    status: str
    children: list["HierarchyNode"] = field(default_factory=list)
    done_leaves: int = 0
    total_leaves: int = 0
    is_current: bool = False
    link_label: Optional[str] = None
    blocked_by: tuple[BackendIdentity, ...] = ()
    blocks: tuple[BackendIdentity, ...] = ()

    @property
    def progress_label(self) -> str:
        if self.link_label is not None:
            suffix = f" — {self.title}" if self.title else ""
            return f"{self.link_label}: {self.identity.display_key}{suffix}"
        total = self.total_leaves
        done = self.done_leaves
        percent = round(100 * done / total) if total else 0
        marker = "★ " if self.is_current else ""
        deps = dependency_suffix(self.blocked_by, self.blocks)
        return (
            f"[{done}/{total} {percent}%] {marker}"
            f"{self.identity.display_key} — {self.title}{deps}"
        )

def compute_progress(node: HierarchyNode) -> None:
    """Fill done_leaves/total_leaves bottom-up (link leaves do not contribute)."""
    progress_children = [child for child in node.children if child.link_label is None]
    for child in progress_children:
        compute_progress(child)
    if node.link_label is not None:
        node.done_leaves = 0
        node.total_leaves = 0
        return
    if not progress_children:
        node.total_leaves = 1
        node.done_leaves = 1 if is_done_status(node.status) else 0
        return
    node.done_leaves = sum(child.done_leaves for child in progress_children)
    node.total_leaves = sum(child.total_leaves for child in progress_children)


def _node_from_summary(
    summary: TaskSummary,
    *,
    is_current: bool = False,
    link_label: Optional[str] = None,
) -> HierarchyNode:
    return HierarchyNode(
        identity=summary.identity,
        title=summary.title,
        status=summary.status,
        is_current=is_current,
        link_label=link_label,
        blocked_by=summary.blocked_by,
        blocks=summary.blocks,
    )


def _node_from_identity(
    identity: BackendIdentity,
    *,
    title: str = "",
    status: str = "Unknown",
    is_current: bool = False,
    link_label: Optional[str] = None,
) -> HierarchyNode:
    return HierarchyNode(
        identity=identity,
        title=title,
        status=status,
        is_current=is_current,
        link_label=link_label,
    )


def build_forest_from_details(details: Mapping[str, TaskDetail]) -> list[HierarchyNode]:
    """Nest parent/child edges among loaded details into a forest of roots."""
    if not details:
        return []
    nodes = {
        stable_id: _node_from_summary(detail.summary)
        for stable_id, detail in details.items()
    }
    children_of: dict[str, list[str]] = defaultdict(list)
    parent_of: dict[str, str] = {}

    def link_parent_child(parent_id: str, child_id: str) -> None:
        if parent_id not in nodes or child_id not in nodes or parent_id == child_id:
            return
        if parent_of.get(child_id) == parent_id:
            return
        if child_id in parent_of:
            return
        stack = [child_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == parent_id:
                return
            if current in seen:
                continue
            seen.add(current)
            stack.extend(children_of.get(current, ()))
        parent_of[child_id] = parent_id
        children_of[parent_id].append(child_id)

    for stable_id, detail in details.items():
        for relation in detail.relationships:
            target_id = relation.target.stable_id
            if relation.kind is RelationshipKind.PARENT:
                link_parent_child(target_id, stable_id)
            elif relation.kind is RelationshipKind.CHILD:
                link_parent_child(stable_id, target_id)

    def attach(stable_id: str, stack: set[str]) -> HierarchyNode:
        node = nodes[stable_id]
        if stable_id in stack:
            return node
        stack.add(stable_id)
        node.children = [
            attach(child_id, stack)
            for child_id in children_of.get(stable_id, ())
            if child_id in nodes
        ]
        stack.remove(stable_id)
        return node

    roots = [attach(stable_id, set()) for stable_id in nodes if stable_id not in parent_of]
    for root in roots:
        compute_progress(root)
    return roots


def build_forest_from_summaries(tasks: Sequence[TaskSummary]) -> list[HierarchyNode]:
    """Nest tasks by TaskSummary.parent when the parent is in the same set."""
    summaries = list(tasks)
    if not summaries:
        return []
    nodes = {task.identity.stable_id: _node_from_summary(task) for task in summaries}
    children_of: dict[str, list[str]] = defaultdict(list)
    parent_of: dict[str, str] = {}

    def link_parent_child(parent_id: str, child_id: str) -> None:
        if parent_id not in nodes or child_id not in nodes or parent_id == child_id:
            return
        if parent_of.get(child_id) == parent_id:
            return
        if child_id in parent_of:
            return
        stack = [child_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == parent_id:
                return
            if current in seen:
                continue
            seen.add(current)
            stack.extend(children_of.get(current, ()))
        parent_of[child_id] = parent_id
        children_of[parent_id].append(child_id)

    for task in summaries:
        if task.parent is not None:
            link_parent_child(task.parent.stable_id, task.identity.stable_id)

    def attach(stable_id: str, stack: set[str]) -> HierarchyNode:
        node = nodes[stable_id]
        if stable_id in stack:
            return node
        stack.add(stable_id)
        node.children = [
            attach(child_id, stack)
            for child_id in children_of.get(stable_id, ())
            if child_id in nodes
        ]
        stack.remove(stable_id)
        return node

    roots = [attach(stable_id, set()) for stable_id in nodes if stable_id not in parent_of]
    for root in roots:
        compute_progress(root)
    return roots


def expand_hierarchy(
    controller: "TasksController",
    seeds: Sequence[TaskSummary],
    *,
    max_depth: int = DEFAULT_TREE_MAX_DEPTH,
    max_nodes: int = DEFAULT_TREE_MAX_NODES,
) -> list[HierarchyNode]:
    """Fetch parent/child details from seeds and return a progress-annotated forest."""
    details: dict[str, TaskDetail] = {}
    queue: list[tuple[BackendIdentity, int]] = [
        (seed.identity, 0) for seed in seeds
    ]
    seen: set[str] = set()
    while queue and len(details) < max_nodes:
        identity, depth = queue.pop(0)
        stable_id = identity.stable_id
        if stable_id in seen:
            continue
        seen.add(stable_id)
        detail, _error = controller.load_detail(identity)
        if detail is None:
            continue
        details[stable_id] = detail
        if depth >= max_depth:
            continue
        for relation in detail.relationships:
            if relation.kind in (RelationshipKind.PARENT, RelationshipKind.CHILD):
                if relation.target.stable_id not in seen:
                    queue.append((relation.target, depth + 1))
    return build_forest_from_details(details)


def _descendants(
    controller: "TasksController",
    detail: TaskDetail,
    *,
    depth: int,
    current_id: str,
) -> HierarchyNode:
    node = _node_from_summary(
        detail.summary,
        is_current=detail.identity.stable_id == current_id,
    )
    if depth > 0:
        for relation in detail.relationships:
            if relation.kind is not RelationshipKind.CHILD:
                continue
            child_detail, _error = controller.load_detail(relation.target)
            if child_detail is not None:
                node.children.append(
                    _descendants(
                        controller,
                        child_detail,
                        depth=depth - 1,
                        current_id=current_id,
                    )
                )
            else:
                node.children.append(
                    _node_from_identity(
                        relation.target,
                        title=relation.summary or "",
                    )
                )
    if node.is_current:
        for relation in detail.relationships:
            if relation.kind in (RelationshipKind.PARENT, RelationshipKind.CHILD):
                continue
            node.children.append(
                _node_from_identity(
                    relation.target,
                    title=relation.summary or "",
                    link_label=relation.label,
                )
            )
    return node


def build_relationship_hierarchy(
    controller: "TasksController",
    detail: TaskDetail,
    *,
    max_ancestors: int = DEFAULT_DETAIL_ANCESTORS,
    max_descendant_depth: int = DEFAULT_DETAIL_DESCENDANT_DEPTH,
) -> HierarchyNode:
    """Ancestor chain above current plus descendants (and other links under current)."""
    current_id = detail.identity.stable_id
    ancestors: list[TaskDetail] = []
    cursor = detail
    seen = {current_id}
    for _ in range(max_ancestors):
        parent_relation = next(
            (
                relation
                for relation in cursor.relationships
                if relation.kind is RelationshipKind.PARENT
            ),
            None,
        )
        if parent_relation is None or parent_relation.target.stable_id in seen:
            break
        parent_detail, _error = controller.load_detail(parent_relation.target)
        if parent_detail is None:
            break
        ancestors.append(parent_detail)
        seen.add(parent_detail.identity.stable_id)
        cursor = parent_detail

    node = _descendants(
        controller,
        detail,
        depth=max_descendant_depth,
        current_id=current_id,
    )
    for ancestor in ancestors:
        parent_node = _node_from_summary(ancestor.summary)
        parent_node.children = [node]
        node = parent_node
    compute_progress(node)
    return node


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


class TasksController:
    """Backend session + list/detail loading shared by screens and tests."""

    def __init__(
        self,
        backend: TaskBackend,
        *,
        initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
        cache_scope: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.backend = backend
        self._initial_assignee_filter = initial_assignee_filter
        self._on_assignee_filter_change = on_assignee_filter_change
        self.cache_scope = cache_scope
        self.cache_dir = cache_dir
        self.detail_cache: dict[str, TaskDetail] = {}
        self.cached_items: dict[str, TaskSummary] = {}
        self._synced_at: Optional[str] = None

    def load_list(
        self,
        state: ListState,
        *,
        refresh: bool = False,
        full: bool = False,
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
    ) -> None:
        state.error = None
        try:
            if self.cache_scope:
                self._load_list_cached(
                    state, refresh=refresh, full=full, on_progress=on_progress
                )
            else:
                runner = PhaseRunner(self._fetch_labels(state, refresh=refresh, full=full), on_progress)
                fetched = self._fetch_tasks(
                    state,
                    runner=runner,
                    updated_since=None,
                    include_closed=False,
                    refresh=refresh,
                    full=full,
                    backend_refresh=refresh,
                )
                state.tasks = list(fetched)
                self.cached_items = {
                    task.identity.stable_id: task for task in state.tasks
                }
            count = len(filter_tasks(state.tasks, state.filter_text))
            state.index = min(max(state.index, 0), max(0, count - 1))
        except Exception as error:  # Backends expose user-ready errors.
            state.error = str(error) or type(error).__name__

    def _fetch_labels(
        self, state: ListState, *, refresh: bool, full: bool
    ) -> list[str]:
        if state.assignee_filter is AssigneeFilter.ME_OR_UNASSIGNED:
            if refresh and not full:
                return ["Fetching @me updates", "Fetching unassigned updates"]
            return ["Fetching @me", "Fetching unassigned"]
        if refresh and not full:
            return ["Fetching updates"]
        return ["Fetching issues"]

    def _fetch_tasks(
        self,
        state: ListState,
        *,
        runner: PhaseRunner,
        updated_since: Optional[str],
        include_closed: bool,
        refresh: bool,
        full: bool,
        backend_refresh: bool,
    ) -> list[TaskSummary]:
        labels = self._fetch_labels(state, refresh=refresh, full=full)
        if state.assignee_filter is AssigneeFilter.ME_OR_UNASSIGNED:
            assigned = runner.run(
                labels[0],
                lambda: list(
                    self.backend.list_tasks(
                        query=state.query,
                        refresh=backend_refresh,
                        assignee_filter=AssigneeFilter.ME,
                        updated_since=updated_since,
                        include_closed=include_closed,
                    )
                ),
            )
            unassigned = runner.run(
                labels[1],
                lambda: list(
                    self.backend.list_tasks(
                        query=state.query,
                        refresh=backend_refresh,
                        assignee_filter=AssigneeFilter.UNASSIGNED,
                        updated_since=updated_since,
                        include_closed=include_closed,
                    )
                ),
            )
            return merge_task_summaries(
                assigned, unassigned, limit=_backend_limit(self.backend)
            )
        return runner.run(
            labels[0],
            lambda: list(
                self.backend.list_tasks(
                    query=state.query,
                    refresh=backend_refresh,
                    assignee_filter=state.assignee_filter,
                    updated_since=updated_since,
                    include_closed=include_closed,
                )
            ),
        )

    def _load_list_cached(
        self,
        state: ListState,
        *,
        refresh: bool,
        full: bool,
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
    ) -> None:
        assert self.cache_scope is not None
        entry = load_entry(
            self.cache_scope,
            state.query,
            state.assignee_filter,
            cache_dir=self.cache_dir,
        )
        if entry is not None and not refresh and not full:
            self.cached_items = dict(entry.items)
            self._synced_at = entry.synced_at
            state.tasks = presentation_tasks(self.cached_items, state.query)
            return

        if entry is not None and refresh and not full:
            labels = self._fetch_labels(state, refresh=True, full=False) + ["Saving cache"]
            runner = PhaseRunner(labels, on_progress)
            since = self._delta_since(entry.synced_at)
            delta = self._fetch_tasks(
                state,
                runner=runner,
                updated_since=since,
                include_closed=True,
                refresh=True,
                full=False,
                backend_refresh=True,
            )

            def save() -> None:
                entry.merge_items(delta)
                entry.synced_at = utc_now_iso()
                save_entry(self.cache_scope, entry, cache_dir=self.cache_dir)

            runner.run("Saving cache", save)
            self.cached_items = dict(entry.items)
            self._synced_at = entry.synced_at
            state.tasks = presentation_tasks(self.cached_items, state.query)
            return

        labels = self._fetch_labels(state, refresh=True, full=True) + ["Saving cache"]
        runner = PhaseRunner(labels, on_progress)
        fetched = self._fetch_tasks(
            state,
            runner=runner,
            updated_since=None,
            include_closed=False,
            refresh=True,
            full=True,
            backend_refresh=True,
        )

        def replace() -> None:
            new_entry = CacheEntry(
                synced_at=utc_now_iso(),
                query=state.query,
                assignee=state.assignee_filter,
            )
            new_entry.replace_items(fetched)
            save_entry(self.cache_scope, new_entry, cache_dir=self.cache_dir)
            self.cached_items = dict(new_entry.items)
            self._synced_at = new_entry.synced_at

        runner.run("Saving cache", replace)
        state.tasks = presentation_tasks(self.cached_items, state.query)

    def _delta_since(self, synced_at: str) -> str:
        label = getattr(self.backend, "backend_label", "")
        if label == "Jira":
            return format_jira_since(synced_at)
        return format_github_since(synced_at)

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
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
    ) -> bool:
        changed = state.assignee_filter is not selection
        if changed:
            state.assignee_filter = selection
            state.index = 0
        if changed or reload_if_unchanged:
            self.load_list(state, on_progress=on_progress)
        if (changed or notify_if_unchanged) and self._on_assignee_filter_change:
            try:
                self._on_assignee_filter_change(selection)
            except Exception as error:
                message = str(error) or type(error).__name__
                state.error = f"{state.error}; {message}" if state.error else message
        return changed

    def clear_filters(
        self,
        state: ListState,
        *,
        on_progress: Optional[Callable[[SyncProgress], None]] = None,
    ) -> bool:
        set_filter(state, "")
        return self.change_assignee_filter(
            state,
            AssigneeFilter.ALL,
            notify_if_unchanged=True,
            on_progress=on_progress,
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
