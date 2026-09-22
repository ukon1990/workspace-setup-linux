"""Textual application entry for the tasks browser."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence

from textual.app import App
from textual.screen import Screen

from ..filters import AssigneeFilter
from ..models import BackendIdentity, TaskSummary
from ..pulls import GithubPullsBackend
from .logic import TaskBackend, TasksController
from .pulls import PullsController
from .screens import DetailScreen, ListScreen


class TasksApp(App[None]):
    """Read-only Jira / GitHub task browser."""

    CSS_PATH = Path(__file__).with_name("app.tcss")
    TITLE = "tasks"

    def __init__(
        self,
        controller: TasksController,
        pulls_controller: PullsController,
        *,
        initial_tasks: Optional[Sequence[TaskSummary]] = None,
        initial_identity: Optional[BackendIdentity] = None,
        query: Optional[str] = None,
        load_list_on_mount: bool = True,
        pulls_error: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.pulls_controller = pulls_controller
        self._initial_tasks = initial_tasks
        self._initial_identity = initial_identity
        self._query = query
        self._load_list_on_mount = load_list_on_mount
        self._pulls_error = pulls_error

    def get_default_screen(self) -> Screen:
        if self._initial_identity is not None:
            return DetailScreen(self.controller, self._initial_identity)
        state = self.controller.make_list_state(
            tasks=self._initial_tasks,
            query=self._query,
        )
        return ListScreen(
            self.controller,
            state,
            self.pulls_controller,
            load_on_mount=self._load_list_on_mount,
            pulls_error=self._pulls_error,
        )


def run(
    backend: TaskBackend,
    *,
    initial_tasks: Optional[Sequence[TaskSummary]] = None,
    initial_identity: Optional[BackendIdentity] = None,
    query: Optional[str] = None,
    initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
    on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
    cache_scope: Optional[str] = None,
    cache_dir: Optional[str] = None,
    pulls_backend: Optional[GithubPullsBackend] = None,
    pulls_error: Optional[str] = None,
    pull_excludes: Sequence[str] = (),
) -> None:
    """Launch the task browser."""
    controller = TasksController(
        backend,
        initial_assignee_filter=initial_assignee_filter,
        on_assignee_filter_change=on_assignee_filter_change,
        cache_scope=cache_scope,
        cache_dir=cache_dir,
    )
    pulls_controller = PullsController(
        pulls_backend,
        exclude_patterns=pull_excludes,
        cache_scope=cache_scope,
        cache_dir=cache_dir,
    )
    TasksApp(
        controller,
        pulls_controller,
        initial_tasks=initial_tasks,
        initial_identity=initial_identity,
        query=query,
        load_list_on_mount=initial_tasks is None,
        pulls_error=pulls_error,
    ).run()
