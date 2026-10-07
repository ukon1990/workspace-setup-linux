"""Completion, inherited blockers and available-work selection shared by both views."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from .models import TaskSummary

DONE_STATUSES = frozenset(
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


def is_done_status(status: str) -> bool:
    return status.casefold().replace("_", " ").strip() in DONE_STATUSES


def is_done(task: TaskSummary) -> bool:
    return task.completed if task.completed is not None else is_done_status(task.status)


class WorkState(str, Enum):
    READY = "Ready"
    BLOCKED = "Blocked"
    DONE = "Done"
    UNKNOWN = "Unknown"


WORK_ICONS = {
    WorkState.DONE: "✓",
    WorkState.READY: "○",
    WorkState.BLOCKED: "x",
    WorkState.UNKNOWN: "?",
}


def work_icon(state: WorkState) -> str:
    return WORK_ICONS.get(state, "?")


@dataclass
class Readiness:
    items: dict[str, TaskSummary] = field(default_factory=dict)
    states: dict[str, WorkState] = field(default_factory=dict)
    ready_descendants: dict[str, int] = field(default_factory=dict)
    candidate_ids: set[str] = field(default_factory=set)
    partial: bool = False

    def selected(self, mode: str) -> list[TaskSummary]:
        ids = set(self.candidate_ids)
        if mode != "all":
            ids = {key for key in ids if self.states.get(key) is WorkState.READY}
            if mode == "available":
                ids.update(
                    key
                    for key, count in self.ready_descendants.items()
                    if count and not is_done(self.items[key])
                )
        return [task for key, task in self.items.items() if key in ids]


def evaluate(
    items: Mapping[str, TaskSummary], candidates: Sequence[TaskSummary], *, partial: bool = False
) -> Readiness:
    """Resolve dependencies, then roll up children independently of view filters."""
    children: dict[str, set[str]] = {key: set() for key in items}
    parents: dict[str, set[str]] = defaultdict(set)
    for key, task in items.items():
        for identity in task.children:
            child = items.get(identity.stable_id)
            # Native parent metadata wins over an older parent's child inventory.
            if child is not None and child.parent is not None and child.parent.stable_id != key:
                continue
            children[key].add(identity.stable_id)
            parents[identity.stable_id].add(key)
        if task.parent is not None:
            parent_id = task.parent.stable_id
            parents[key].add(parent_id)
            if parent_id in items:
                children[parent_id].add(key)

    states = {}
    for key, task in items.items():
        if is_done(task):
            states[key] = WorkState.DONE
            continue
        pending_ancestors = [(key, frozenset())]
        processed = set()
        unknown = False
        blocked = False
        while pending_ancestors:
            current_id, path = pending_ancestors.pop()
            if current_id in path:
                unknown = True
                continue
            if current_id in processed:
                continue
            processed.add(current_id)
            current = items.get(current_id)
            if current is None:
                unknown = True
                continue
            unknown |= not current.dependencies_complete or len(parents[current_id]) > 1
            unknown |= (
                current.status.casefold().strip() in {"", "unknown"} and current.completed is None
            )
            for identity in current.blocked_by:
                blocker = items.get(identity.stable_id)
                if (
                    blocker is None
                    or blocker.status.casefold() == "unknown"
                    and blocker.completed is None
                ):
                    unknown = True
                elif not is_done(blocker):
                    blocked = True
            pending_ancestors.extend(
                (parent, path | {current_id}) for parent in parents[current_id]
            )
        states[key] = (
            WorkState.BLOCKED if blocked else WorkState.UNKNOWN if unknown else WorkState.READY
        )

    # Dependency states are fixed before child rollup, so siblings cannot block
    # one another merely through the feature's rolled-up state.
    dependency_states = states.copy()
    # A child inventory cycle is invalid hierarchy, even if it also contains
    # a ready leaf. Explicit blockers and completion still dominate that error.
    for key, value in list(dependency_states.items()):
        if value is not WorkState.READY:
            continue
        pending_children = list(children[key])
        visited = set()
        while pending_children:
            child = pending_children.pop()
            if child == key:
                dependency_states[key] = states[key] = WorkState.UNKNOWN
                break
            if child in visited or states.get(child) is WorkState.DONE:
                continue
            visited.add(child)
            pending_children.extend(children.get(child, ()))

    pending = deque(key for key, value in dependency_states.items() if value is WorkState.READY)
    queued = set(pending)
    # Unknown is the conservative starting point. Proven-ready leaves and
    # proven-blocked branches propagate until stable; invalid cycles stay unknown.
    for key in pending:
        states[key] = WorkState.UNKNOWN
    while pending:
        key = pending.popleft()
        queued.remove(key)
        unfinished = [child for child in children[key] if states.get(child) is not WorkState.DONE]
        complete = getattr(items[key], "children_complete", True)
        if any(states.get(child) is WorkState.READY for child in unfinished):
            value = WorkState.READY
        elif complete and not unfinished:
            value = WorkState.READY
        elif complete and all(states.get(child) is WorkState.BLOCKED for child in unfinished):
            value = WorkState.BLOCKED
        else:
            value = WorkState.UNKNOWN
        if value is states[key]:
            continue
        states[key] = value
        for parent in parents[key]:
            if dependency_states.get(parent) is WorkState.READY and parent not in queued:
                pending.append(parent)
                queued.add(parent)

    candidate_ids = {task.identity.stable_id for task in candidates}
    descendants: dict[str, set[str]] = {key: set() for key in items}
    for key in candidate_ids:
        if states.get(key) is not WorkState.READY:
            continue
        pending_parents = list(parents[key])
        seen = {key}
        while pending_parents:
            parent = pending_parents.pop()
            if parent in seen or parent not in items:
                continue
            seen.add(parent)
            descendants[parent].add(key)
            pending_parents.extend(parents[parent])
    return Readiness(
        dict(items),
        states,
        {key: len(ids) for key, ids in descendants.items()},
        candidate_ids,
        partial,
    )
