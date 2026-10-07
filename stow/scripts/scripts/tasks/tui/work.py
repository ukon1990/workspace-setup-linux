"""Bounded supporting-data resolution and available-work presentation."""

from dataclasses import replace

from ..filters import WorkFilter
from ..readiness import WorkState


class WorkController:
    def resolve_readiness(
        self, seeds, *, refresh=False, full=False, on_progress=None, max_loads=80, skip_ids=()
    ):
        from .resolution import ReadinessResolver

        if refresh or full:
            self.detail_cache.clear()
        resolver = ReadinessResolver(
            self,
            seeds,
            refresh=refresh,
            on_progress=on_progress,
            max_loads=max_loads,
            skip_ids=skip_ids,
        )
        result = resolver.run()
        self.last_readiness_loads = resolver.loads
        self.last_readiness_failures = resolver.failed
        return result

    def resolve_work(self, state, *, refresh=False, full=False, on_progress=None):
        from .logic import _backend_limit

        state.readiness = self.resolve_readiness(
            state.tasks, refresh=refresh, full=full, on_progress=on_progress
        )
        limit = _backend_limit(self.backend)
        state.readiness.partial = bool(limit and len(state.tasks) >= limit)

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
            text += f" · {unknown} unknown (unresolved dependencies, ancestors, or children)"
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
