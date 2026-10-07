"""Backend session and cached list loading."""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from ..cache import (
    CacheEntry,
    format_github_since,
    format_jira_since,
    load_entry,
    save_entry,
    utc_now_iso,
)
from ..filters import AssigneeFilter, WorkFilter
from ..models import BackendIdentity, TaskDetail, TaskSummary
from .hierarchy_sync import HierarchySync
from .logic import (
    ListState,
    PhaseRunner,
    SyncProgress,
    TaskBackend,
    _backend_limit,
    merge_task_summaries,
    presentation_tasks,
    set_filter,
)
from .sync import PersistentIssues
from .work import WorkController


class TasksController(PersistentIssues, HierarchySync, WorkController):
    """Backend session + list/detail loading shared by screens and tests."""

    def __init__(
        self,
        backend: TaskBackend,
        *,
        initial_assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        initial_work_filter: WorkFilter = WorkFilter.ALL,
        on_work_filter_change: Optional[Callable[[WorkFilter], None]] = None,
        on_assignee_filter_change: Optional[Callable[[AssigneeFilter], None]] = None,
        cache_scope: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.backend = backend
        self._initial_work_filter = initial_work_filter
        self._on_work_filter_change = on_work_filter_change
        self._initial_assignee_filter = initial_assignee_filter
        self._on_assignee_filter_change = on_assignee_filter_change
        self.cache_scope = cache_scope
        self.cache_dir = cache_dir
        self.detail_cache: dict[str, TaskDetail] = {}
        self.cached_items: dict[str, TaskSummary] = {}
        self._synced_at: Optional[str] = None
        self.issue_stores = {}
        self.rebuild_backups = {}
        self.dependency_links = {}
        self.checked_scopes = set()
        self.changed_ids = set()
        self.sync_warning = None
        self.sync_warnings = {}
        self.presentation_items = None

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
            if self.persistent_sync:
                self.load_persistent_list(
                    state, refresh=refresh, full=full, on_progress=on_progress
                )
            elif self.cache_scope:
                self._load_list_cached(state, refresh=refresh, full=full, on_progress=on_progress)
            else:
                runner = PhaseRunner(
                    self._fetch_labels(state, refresh=refresh, full=full), on_progress
                )
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
                self.cached_items = {task.identity.stable_id: task for task in state.tasks}
            state.changed_ids = self.changed_ids
            self.resolve_work(
                state,
                refresh=refresh and not self.persistent_sync,
                full=full and not self.persistent_sync,
                on_progress=on_progress,
            )
            from .logic import visible_tasks

            count = len(visible_tasks(state))
            state.index = min(max(state.index, 0), max(0, count - 1))
        except Exception as error:  # Backends expose user-ready errors.
            state.error = str(error) or type(error).__name__

    def _fetch_labels(self, state: ListState, *, refresh: bool, full: bool) -> list[str]:
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
            return merge_task_summaries(assigned, unassigned, limit=_backend_limit(self.backend))
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
        if self.persistent_sync:
            if refresh:
                self.sync_scope(self.scope_for_identity(identity), refresh=True)
            return self.load_persistent_detail(identity)
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
        self.change_work_filter(state, WorkFilter.ALL)
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
        work_filter: Optional[WorkFilter] = None,
    ) -> ListState:
        return ListState(
            list(tasks or ()),
            query=query,
            changed_ids=self.changed_ids,
            work_filter=work_filter if work_filter is not None else self._initial_work_filter,
            assignee_filter=(
                assignee_filter if assignee_filter is not None else self._initial_assignee_filter
            ),
        )
