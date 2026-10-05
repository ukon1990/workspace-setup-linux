"""Completion, inherited blockers and available-work selection shared by both views."""

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
    """Evaluate all ancestors before filtering; count only matching ready candidates."""
    states = {}
    for key, task in items.items():
        if is_done(task):
            states[key] = WorkState.DONE
            continue
        current = task
        seen = set()
        unknown = False
        blocked = False
        while current is not None:
            current_id = current.identity.stable_id
            if current_id in seen:
                unknown = True
                break
            seen.add(current_id)
            unknown |= not current.dependencies_complete
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
            if current.parent is None:
                break
            parent = items.get(current.parent.stable_id)
            if parent is None:
                unknown = True
                break
            current = parent
        if task.status.casefold() == "unknown" and task.completed is None:
            unknown = True
        states[key] = (
            WorkState.BLOCKED if blocked else WorkState.UNKNOWN if unknown else WorkState.READY
        )

    candidate_ids = {task.identity.stable_id for task in candidates}
    descendants: dict[str, set[str]] = {key: set() for key in items}
    for key in candidate_ids:
        if states.get(key) is not WorkState.READY:
            continue
        current = items.get(key)
        seen = {key}
        while current is not None and current.parent is not None:
            parent_id = current.parent.stable_id
            if parent_id in seen or parent_id not in items:
                break
            seen.add(parent_id)
            descendants[parent_id].add(key)
            current = items[parent_id]
    return Readiness(
        dict(items),
        states,
        {key: len(ids) for key, ids in descendants.items()},
        candidate_ids,
        partial,
    )
