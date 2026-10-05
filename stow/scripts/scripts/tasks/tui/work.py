"""Bounded supporting-data resolution and available-work presentation."""

from collections import deque
from dataclasses import replace

from ..filters import WorkFilter
from ..readiness import WorkState, evaluate


class WorkController:
    def resolve_work(self, state, *, refresh=False, full=False, on_progress=None):
        from .logic import SyncProgress, _backend_limit

        if refresh or full:
            self.detail_cache.clear()
        # Cached closed issues contribute completion progress and blocker status.
        items = dict(self.cached_items)
        items.update((task.identity.stable_id, task) for task in state.tasks)
        queue = deque((task.identity, 0, True) for task in state.tasks)
        candidate_ids = {task.identity.stable_id for task in state.tasks}
        seen = set()
        fetched = set()
        loads = 0
        while queue:
            identity, depth, follow_parents = queue.popleft()
            key = identity.stable_id
            token = (key, follow_parents)
            if token in seen:
                continue
            seen.add(token)
            task = items.get(key)
            # List metadata is preferred; fetch only absent/incomplete summaries.
            if key not in fetched and (
                task is None
                or not task.dependencies_complete
                or (refresh and key not in candidate_ids and key not in fetched)
            ):
                if loads >= 80 or depth > 8:
                    if key not in candidate_ids:
                        items.pop(key, None)
                    continue
                loads += 1
                if on_progress:
                    on_progress(
                        SyncProgress(
                            loads,
                            0,
                            f"Checking dependencies · {loads} loaded · {identity.display_key}",
                        )
                    )
                fetched.add(key)
                detail, _error = self.load_detail(identity, refresh=refresh)
                if detail is None:
                    items.pop(key, None)
                    continue
                task = detail.summary
                items[key] = task
            if task is None or not follow_parents or depth >= 8:
                continue
            if task.parent is not None:
                queue.append((task.parent, depth + 1, True))
            queue.extend((blocker, depth + 1, False) for blocker in task.blocked_by)
        limit = _backend_limit(self.backend)
        state.readiness = evaluate(
            items, state.tasks, partial=bool(limit and len(state.tasks) >= limit)
        )

    def change_work_filter(self, state, selection):
        state.work_filter = selection
        state.index = 0
        if self._on_work_filter_change:
            try:
                self._on_work_filter_change(selection)
            except Exception as error:
                state.error = str(error) or type(error).__name__

    def work_label(self, state, task):
        from .logic import work_result

        return work_result(state).states.get(task.identity.stable_id, WorkState.UNKNOWN).value

    def ready_descendant_count(self, state, task):
        from .logic import work_result

        return work_result(state).ready_descendants.get(task.identity.stable_id, 0)

    def work_status(self, state):
        from .logic import work_result

        result = work_result(state)
        ready = sum(result.states.get(key) is WorkState.READY for key in result.candidate_ids)
        unknown = sum(result.states.get(key) is WorkState.UNKNOWN for key in result.candidate_ids)
        changed = len(self.changed_ids)
        text = f"work: {state.work_filter.label} · {ready} ready · {changed} changed"
        if self.sync_warning:
            text += f" · Stale: {self.sync_warning}"
        if unknown:
            text += f" · {unknown} unknown (unresolved dependencies or ancestors)"
        if result.partial:
            text += " · counts may be partial (issue limit reached)"
        return text

    def build_work_forest(self, state):
        from .hierarchy import build_forest_from_summaries
        from .logic import work_result

        result = work_result(state)
        # Build and compute completion progress before pruning or promotion.
        items = dict(self.cached_items)
        items.update(result.items)
        eligible = {task.identity.stable_id for task in result.selected(state.work_filter.value)}
        if state.work_filter is WorkFilter.ALL:
            eligible = set(result.candidate_ids)
            # Preserve existing All tree behavior, including cached completed rows.
            from .logic import filter_tasks

            eligible.update(
                task.identity.stable_id
                for task in filter_tasks(
                    list(
                        (
                            self.presentation_items
                            if self.presentation_items is not None
                            else self.cached_items
                        ).values()
                    ),
                    state.filter_text,
                )
            )
        forest = build_forest_from_summaries(list(items.values()))

        def prune(nodes):
            kept = []
            for node in nodes:
                children = prune(node.children)
                key = node.identity.stable_id
                if key in eligible:
                    kept.append(
                        replace(
                            node,
                            children=children,
                            work_label=result.states.get(key, WorkState.DONE).value,
                            changed=key in self.changed_ids,
                            ready_descendants=result.ready_descendants.get(key, 0),
                        )
                    )
                else:
                    kept.extend(children)
            return kept

        return prune(forest)
