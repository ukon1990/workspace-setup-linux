"""Bounded resolution of the unfiltered hierarchy used to classify work."""

from collections import deque
from dataclasses import replace

from ..models import Backend, RelationshipKind
from ..readiness import evaluate, is_done

MAX_DEPTH = 8
MAX_LOOKUPS = 80


class ReadinessResolver:
    def __init__(
        self, controller, seeds, *, refresh=False, on_progress=None, max_loads=80, skip_ids=()
    ):
        self.controller = controller
        self.seeds = list(seeds)
        self.refresh = refresh
        self.on_progress = on_progress
        self.max_loads = max(0, min(MAX_LOOKUPS, max_loads))
        self.loads = 0
        self.items = dict(controller.cached_items)
        for seed in seeds:
            self.items.setdefault(seed.identity.stable_id, seed)
        self.queue = deque((seed.identity, 0, True) for seed in seeds)
        self.seen = set()
        self.fetched = set(skip_ids)
        self.failed = set(skip_ids)
        self.queried = set()
        self.dirty_scopes = set()
        self.pending = set()
        self.pending_scopes = {}
        self.scanned_scopes = set()
        for seed in seeds:
            self._scan_scope(controller.scope_for_identity(seed.identity))
        self._detail_hints()

    def _scan_scope(self, scope):
        if scope in self.scanned_scopes:
            return
        self.scanned_scopes.add(scope)
        for key, task in self.controller.cached_items.items():
            if (
                not task.dependencies_complete
                and self.controller.scope_for_identity(task.identity) == scope
            ):
                self.items[key] = task
                self.pending.add(key)
                self.pending_scopes[key] = scope
                self.queue.append((task.identity, 0, False))

    def _progress(self, label):
        if self.on_progress:
            from .logic import SyncProgress

            self.on_progress(SyncProgress(self.loads, 0, label))

    def _remember(self, task):
        task = self.controller.remember_hierarchy_summary(task)
        self.items[task.identity.stable_id] = task
        self.dirty_scopes.add(self.controller.scope_for_identity(task.identity))
        return task

    def _detail_hints(self):
        for detail in self.controller.detail_cache.values():
            key = detail.identity.stable_id
            task = self.items.get(key, detail.summary)
            children = dict.fromkeys(task.children)
            blockers = dict.fromkeys(task.blocked_by)
            parent = task.parent
            for relation in detail.relationships:
                if relation.kind is RelationshipKind.CHILD:
                    # A resolved move wins over an older cached relationship list.
                    child = self.items.get(relation.target.stable_id)
                    if (
                        not task.children_complete
                        or relation.target.stable_id in {item.stable_id for item in task.children}
                    ) and (
                        child is None
                        or child.parent is None
                        or child.parent.stable_id == task.identity.stable_id
                    ):
                        children[relation.target] = None
                elif relation.kind is RelationshipKind.PARENT and parent is None:
                    parent = relation.target
                elif relation.kind is RelationshipKind.BLOCKED_BY:
                    blockers[relation.target] = None
            self.items[key] = replace(
                task, children=tuple(children), blocked_by=tuple(blockers), parent=parent
            )

    def _load(self, identity):
        key = identity.stable_id
        if key in self.fetched or self.loads >= self.max_loads:
            return None
        self.fetched.add(key)
        self.loads += 1
        self._progress(f"Checking work · {self.loads} lookups · {identity.display_key}")
        detail, _error = self.controller.load_detail(identity, refresh=self.refresh)
        if detail is None:
            self.failed.add(key)
            known = self.items.get(key)
            if known is not None and is_done(known):
                return known
            self.items.pop(key, None)
            return None
        if detail.summary.dependencies_complete:
            self.pending.discard(key)
        task = self._remember(detail.summary)
        self._detail_hints()
        return self.items.get(key, task)

    def _children(self, parents):
        lookup = getattr(self.controller.backend, "list_children", None)
        parents = [task for task, _depth in parents]
        if not parents or not callable(lookup) or self.loads >= self.max_loads:
            return
        self.loads += 1
        self._progress(f"Checking children · {len(parents)} parents")
        self.queried.update(task.identity.stable_id for task in parents)
        try:
            batch = lookup([task.identity for task in parents])
        except Exception:
            return
        children = {task.identity.stable_id: {} for task in parents}
        for child in batch.items:
            if child.parent is None or child.parent.stable_id not in children:
                continue
            children[child.parent.stable_id][child.identity.stable_id] = child.identity
            key = child.identity.stable_id
            if key in self.items or self.loads < self.max_loads:
                if key not in self.items:
                    self.loads += 1
                self._remember(child)
        for parent in parents:
            key = parent.identity.stable_id
            identities = children[key]
            if not batch.complete:
                identities.update((child.stable_id, child) for child in parent.children)
            self._remember(
                replace(
                    parent, children=tuple(identities.values()), children_complete=batch.complete
                )
            )

    def run(self):
        while self.queue:
            frontier = []
            while self.queue:
                identity, depth, follow = self.queue.popleft()
                key = identity.stable_id
                token = (key, follow)
                if token in self.seen:
                    continue
                self.seen.add(token)
                if self.controller.persistent_sync:
                    self.controller.sync_scope(self.controller.scope_for_identity(identity))
                    self._scan_scope(self.controller.scope_for_identity(identity))
                    cached = self.controller.cached_items.get(key)
                    if cached is not None:
                        self.items[key] = cached
                task = self.items.get(key)
                if task is not None and is_done(task) and key not in self.pending:
                    continue
                needs_detail = (
                    task is None
                    or not task.dependencies_complete
                    or (
                        follow and identity.backend is Backend.GITHUB and not task.children_complete
                    )
                    or (
                        self.refresh and key not in {seed.identity.stable_id for seed in self.seeds}
                    )
                )
                if needs_detail and key not in self.fetched and depth <= MAX_DEPTH:
                    loaded = self._load(identity)
                    if loaded is not None:
                        task = loaded
                if task is None or is_done(task) or not follow or depth >= MAX_DEPTH:
                    continue
                frontier.append((task, depth))
            missing_children = [
                (task, depth)
                for task, depth in frontier
                if task.identity.backend is Backend.JIRA
                and not task.children_complete
                and task.identity.stable_id not in self.queried
            ]
            self._children(missing_children)
            # Metadata calls may have reconciled parent moves in another cached node.
            self.items.update(self.controller.cached_items)
            self._detail_hints()
            for key in self.failed:
                known = self.items.get(key)
                if known is None or not is_done(known):
                    self.items.pop(key, None)
            for original, depth in frontier:
                task = self.items.get(original.identity.stable_id, original)
                if task.parent is not None:
                    self.queue.append((task.parent, depth + 1, True))
                self.queue.extend((blocker, depth + 1, False) for blocker in task.blocked_by)
                self.queue.extend((child, depth + 1, True) for child in task.children)
        if self.pending:
            scopes = {self.pending_scopes[key] for key in self.pending}
            self.items = {
                key: replace(task, children_complete=False)
                if self.controller.scope_for_identity(task.identity) in scopes
                else task
                for key, task in self.items.items()
            }
        for scope in self.dirty_scopes:
            if self.controller.persistent_sync:
                self.controller._save_issue_store(scope)
        return evaluate(self.items, self.seeds)
