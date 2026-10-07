"""Hierarchy construction and completion progress."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Mapping, Optional, Sequence

from ..models import BackendIdentity, RelationshipKind, TaskDetail, TaskSummary
from ..readiness import WorkState, evaluate, is_done_status, work_icon
from .logic import dependency_suffix

if TYPE_CHECKING:
    from .controller import TasksController
DEFAULT_TREE_MAX_DEPTH = 8
DEFAULT_TREE_MAX_NODES = 80
DEFAULT_DETAIL_ANCESTORS = 8
DEFAULT_DETAIL_DESCENDANT_DEPTH = 2


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
    work_label: str = ""
    ready_descendants: int = 0
    completed: Optional[bool] = None
    completion_icon: str = ""
    changed: bool = False

    @property
    def progress_label(self) -> str:
        prefix = f"{self.completion_icon} " if self.completion_icon else ""
        key = self.identity.display_key + ("*" if self.changed else "")
        if self.link_label is not None:
            suffix = f" — {self.title}" if self.title else ""
            return f"{prefix}{self.link_label}: {key}{suffix}"
        total = self.total_leaves
        done = self.done_leaves
        percent = round(100 * done / total) if total else 0
        marker = "★ " if self.is_current else ""
        deps = dependency_suffix(self.blocked_by, self.blocks)
        return f"{prefix}[{done}/{total} {percent}%] {marker}{key} — {self.title}{deps}" + (
            f" · {self.work_label} · {self.ready_descendants} ready descendants"
            if self.work_label
            else ""
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
        node.done_leaves = int(
            node.completed if node.completed is not None else is_done_status(node.status)
        )
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
        completed=summary.completed,
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
    nodes = {stable_id: _node_from_summary(detail.summary) for stable_id, detail in details.items()}
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
    queue: list[tuple[BackendIdentity, int]] = [(seed.identity, 0) for seed in seeds]
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
    load_detail: Callable[[BackendIdentity], Optional[TaskDetail]],
    load_link: Callable[[BackendIdentity], Optional[TaskSummary]],
) -> HierarchyNode:
    node = _node_from_summary(
        detail.summary,
        is_current=detail.identity.stable_id == current_id,
    )
    if depth > 0:
        for relation in detail.relationships:
            if relation.kind is not RelationshipKind.CHILD:
                continue
            child_detail = load_detail(relation.target)
            if child_detail is not None:
                node.children.append(
                    _descendants(
                        controller,
                        child_detail,
                        depth=depth - 1,
                        current_id=current_id,
                        load_detail=load_detail,
                        load_link=load_link,
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
            summary = load_link(relation.target)
            if summary is None:
                linked_node = _node_from_identity(
                    relation.target,
                    title=relation.summary or "",
                    link_label=relation.label,
                )
            else:
                linked_node = _node_from_summary(summary, link_label=relation.label)
                # Retain the relationship's original display identity and title.
                linked_node.identity = relation.target
                linked_node.title = relation.summary or ""
            node.children.append(linked_node)
    return node


def build_relationship_hierarchy(
    controller: "TasksController",
    detail: TaskDetail,
    *,
    max_ancestors: int = DEFAULT_DETAIL_ANCESTORS,
    max_descendant_depth: int = DEFAULT_DETAIL_DESCENDANT_DEPTH,
    refresh: bool = False,
) -> HierarchyNode:
    """Ancestor chain above current plus descendants (and other links under current)."""
    resolve = getattr(controller, "resolve_readiness", None)
    normalize = getattr(controller, "hierarchy_detail", lambda target: target)
    resolution_loads = 0
    failed_ids = set()
    if callable(resolve):
        resolve([detail.summary], refresh=refresh, max_loads=DEFAULT_TREE_MAX_NODES)
        resolution_loads = getattr(controller, "last_readiness_loads", 0)
        failed_ids.update(getattr(controller, "last_readiness_failures", ()))
        detail = normalize(detail)
    loaded: dict[str, Optional[TaskDetail]] = {detail.identity.stable_id: detail}
    link_loads = 0

    def load_detail(identity: BackendIdentity) -> Optional[TaskDetail]:
        nonlocal link_loads
        key = identity.stable_id
        if key in failed_ids:
            loaded[key] = None
        if key not in loaded:
            cached = controller.detail_cache.get(key)
            summary = controller.cached_items.get(key)
            if callable(resolve) and (cached is not None or summary is not None):
                loaded[key] = normalize(cached if cached is not None else TaskDetail(summary))
            elif callable(resolve) and resolution_loads + link_loads >= DEFAULT_TREE_MAX_NODES:
                loaded[key] = None
            else:
                link_loads += 1
                target, _error = controller.load_detail(
                    identity, refresh=refresh if not callable(resolve) else False
                )
                loaded[key] = normalize(target) if target is not None else None
                if target is None:
                    failed_ids.add(key)
        return loaded[key]

    def load_link(identity: BackendIdentity) -> Optional[TaskSummary]:
        key = identity.stable_id
        if key in loaded:
            return loaded[key].summary if loaded[key] is not None else None
        if not refresh or callable(resolve):
            cached = controller.detail_cache.get(key)
            summary = cached.summary if cached is not None else controller.cached_items.get(key)
            if summary is not None:
                loaded[key] = normalize(cached if cached is not None else TaskDetail(summary))
                return loaded[key].summary
        if resolution_loads + link_loads >= DEFAULT_TREE_MAX_NODES:
            return None
        target = load_detail(identity)
        return target.summary if target is not None else None

    current_id = detail.identity.stable_id
    ancestors: list[HierarchyNode] = []
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
        parent_detail = load_detail(parent_relation.target)
        if parent_detail is None:
            ancestors.append(
                _node_from_identity(parent_relation.target, title=parent_relation.summary or "")
            )
            break
        ancestors.append(_node_from_summary(parent_detail.summary))
        seen.add(parent_detail.identity.stable_id)
        cursor = parent_detail

    node = _descendants(
        controller,
        detail,
        depth=max_descendant_depth,
        current_id=current_id,
        load_detail=load_detail,
        load_link=load_link,
    )
    for ancestor in ancestors:
        ancestor.children = [node]
        node = ancestor
    compute_progress(node)

    seeds = [target.summary for target in loaded.values() if target is not None]
    if callable(resolve):
        readiness = resolve(
            seeds,
            refresh=False,
            max_loads=max(0, DEFAULT_TREE_MAX_NODES - resolution_loads - link_loads),
            skip_ids=failed_ids,
        )
    else:
        items = dict(getattr(controller, "cached_items", {}))
        items.update((target.identity.stable_id, target) for target in seeds)
        readiness = evaluate(items, seeds)

    def annotate(current: HierarchyNode) -> None:
        current.changed = current.identity.stable_id in getattr(controller, "changed_ids", ())
        state = readiness.states.get(current.identity.stable_id, WorkState.UNKNOWN)
        current.completion_icon = work_icon(state)
        for child in current.children:
            annotate(child)

    annotate(node)
    return node
