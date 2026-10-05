"""Scope-wide incremental sync and persistent issue detail loading."""

from datetime import datetime

from ..cache import CacheEntry, CacheError, load_entry, save_entry, utc_now_iso
from ..issue_cache import IssueStore, load_store, save_store, version_order
from ..models import Backend


class PersistentIssues:
    @property
    def persistent_sync(self):
        return bool(self.cache_scope and callable(getattr(self.backend, "list_updates", None)))

    @property
    def sync_revision(self):
        return tuple(sorted((scope, store.revision) for scope, store in self.issue_stores.items()))

    @staticmethod
    def scope_for_identity(identity):
        if identity.backend is Backend.GITHUB:
            return f"github:{identity.repository}"
        return f"jira:{identity.key.rsplit('-', 1)[0]}"

    def _warn(self, scope, message):
        self.sync_warnings[scope] = message
        self.sync_warning = "; ".join(self.sync_warnings.values())

    def _issue_store(self, scope):
        if scope not in self.issue_stores:
            try:
                self.issue_stores[scope] = load_store(scope, self.cache_dir)
            except CacheError as error:
                self._warn(scope, str(error))
                self.issue_stores[scope] = IssueStore()
        return self.issue_stores[scope]

    def _hydrate(self, store):
        self.cached_items.update(store.items)
        for key in store.items:
            if key not in store.details:
                self.detail_cache.pop(key, None)
        for key, detail in store.details.items():
            self.detail_cache[key] = detail
            self.dependency_links[key] = tuple(relation.target for relation in detail.relationships)

    def _save_issue_store(self, scope):
        try:
            save_store(scope, self._issue_store(scope), self.cache_dir)
            return True
        except (CacheError, OSError) as error:
            self._warn(scope, str(error))
            return False

    def sync_scope(self, scope=None, *, refresh=False, full=False, on_progress=None):
        """Check a scope once on startup, again on r, without display filters."""
        if not self.persistent_sync:
            return
        from .logic import SyncProgress

        scope = scope or self.cache_scope
        if scope not in self.checked_scopes or refresh or full:
            self.sync_warnings.pop(scope, None)
            self.sync_warning = "; ".join(self.sync_warnings.values()) or None
        store = self._issue_store(scope)
        if scope in self.checked_scopes and not refresh and not full:
            self._hydrate(store)
            return
        self.checked_scopes.add(scope)
        self._hydrate(store)
        started_at = utc_now_iso()
        if on_progress:
            on_progress(SyncProgress(0, 0, f"Checking updates · {scope}"))
        if full:
            self.rebuild_backups[scope] = store
            for key in store.items:
                self.cached_items.pop(key, None)
                self.detail_cache.pop(key, None)
            store = IssueStore(revision=store.revision + 1)
            self.issue_stores[scope] = store
        previous = store.synced_at
        if previous is None:
            store.synced_at = started_at
            self._hydrate(store)
            return
        try:
            batch = self.backend.list_updates(scope, previous)
            changed = False
            for task in batch.items:
                key = task.identity.stable_id
                old = store.items.get(key)
                order = version_order(task.updated_at, old.updated_at) if old is not None else None
                if old is not None and (
                    (order == 0 and (task.updated_at is not None or old == task))
                    or order == -1
                    or (task.updated_at is None and old.updated_at is not None)
                ):
                    continue
                store.items[key] = task
                store.details.pop(key, None)
                self.detail_cache.pop(key, None)
                if old is not None or self._after(task.updated_at, previous):
                    self.changed_ids.add(key)
                changed = True
            if changed:
                store.revision += 1
            if batch.complete:
                store.synced_at = started_at
            else:
                self._warn(scope, f"Incomplete update check for {scope}; saved data may be stale")
            if not self._save_issue_store(scope):
                store.synced_at = previous
            self._hydrate(store)
        except Exception as error:
            self._warn(scope, f"Update check failed for {scope}: {error}; using saved data")
            self._hydrate(store)

    @staticmethod
    def _after(timestamp, baseline):
        if timestamp is None:
            return False
        try:
            return datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ) > datetime.fromisoformat(baseline.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False

    def load_persistent_list(self, state, *, refresh=False, full=False, on_progress=None):
        from .logic import PhaseRunner, presentation_tasks

        try:
            entry = load_entry(
                self.cache_scope, state.query, state.assignee_filter, cache_dir=self.cache_dir
            )
        except CacheError as error:
            self._warn(self.cache_scope, str(error))
            entry = None
        self.sync_scope(refresh=refresh, full=full, on_progress=on_progress)
        store = self._issue_store(self.cache_scope)
        if entry is None or full or entry.revision != store.revision:
            try:
                runner = PhaseRunner(
                    self._fetch_labels(state, refresh=False, full=False), on_progress
                )
                tasks = self._fetch_tasks(
                    state,
                    runner=runner,
                    updated_since=None,
                    include_closed=False,
                    refresh=False,
                    full=False,
                    backend_refresh=True,
                )
                for task in tasks:
                    self._merge_fetched_summary(store, task)
                self.rebuild_backups.pop(self.cache_scope, None)
                entry = CacheEntry(
                    synced_at=store.synced_at or utc_now_iso(),
                    query=state.query,
                    assignee=state.assignee_filter,
                    revision=store.revision,
                )
                entry.replace_items(tasks)
                save_entry(self.cache_scope, entry, cache_dir=self.cache_dir)
                self._save_issue_store(self.cache_scope)
            except Exception as error:
                if entry is None:
                    raise
                self._warn(self.cache_scope, f"List update failed: {error}; using saved membership")
                if full and self.cache_scope in self.rebuild_backups:
                    store = self.rebuild_backups.pop(self.cache_scope)
                    self.issue_stores[self.cache_scope] = store
        self._hydrate(store)
        membership = {key: store.items.get(key, task) for key, task in entry.items.items()}
        self.presentation_items = membership
        state.tasks = presentation_tasks(membership, state.query)
        self.sync_dependencies(state.tasks, refresh=refresh, on_progress=on_progress)
        self._synced_at = store.synced_at

    def _merge_fetched_summary(self, store, task):
        key = task.identity.stable_id
        old = store.items.get(key)
        order = version_order(task.updated_at, old.updated_at) if old is not None else None
        if old is not None and (
            order == -1
            or (order == 0 and old.dependencies_complete and not task.dependencies_complete)
        ):
            return
        if old is not None and order != 0:
            store.revision += 1
            self.changed_ids.add(key)
            store.details.pop(key, None)
            self.detail_cache.pop(key, None)
        store.items[key] = task

    def sync_dependencies(self, tasks, *, refresh=False, on_progress=None, skip_scope=None):
        """Sync known supporting scopes before readiness or relationships render."""
        skip_scope = skip_scope or self.cache_scope
        queue = [getattr(task, "identity", task) for task in tasks]
        seen = set()
        scopes = set()
        while queue:
            identity = queue.pop()
            key = identity.stable_id
            if key in seen:
                continue
            seen.add(key)
            scope = self.scope_for_identity(identity)
            if scope not in scopes and scope != skip_scope:
                self.sync_scope(scope, refresh=refresh, on_progress=on_progress)
                scopes.add(scope)
            summary = self.cached_items.get(key)
            if summary is not None:
                queue.extend(summary.blocked_by)
                if summary.parent is not None:
                    queue.append(summary.parent)
            queue.extend(self.dependency_links.get(key, ()))
            detail = self.detail_cache.get(key)
            if detail is not None:
                queue.extend(relation.target for relation in detail.relationships)

    def sync_detail_dependencies(self, identity, *, refresh=False, on_progress=None):
        self.sync_dependencies(
            [identity],
            refresh=refresh,
            on_progress=on_progress,
            skip_scope=self.scope_for_identity(identity),
        )

    def load_persistent_detail(self, identity):
        scope = self.scope_for_identity(identity)
        self.sync_scope(scope)
        store = self._issue_store(scope)
        key = identity.stable_id
        if key in store.details:
            detail = store.details[key]
            store.details.move_to_end(key)
            self._save_issue_store(scope)
            return detail, None
        try:
            detail = self.backend.get_task(identity, refresh=False)
        except Exception as error:
            backup = self.rebuild_backups.pop(scope, None)
            if backup is not None:
                self.issue_stores[scope] = backup
                self._hydrate(backup)
                if key in backup.details:
                    self._warn(scope, f"Rebuild failed: {error}; using saved data")
                    return backup.details[key], None
            return None, str(error) or type(error).__name__
        self._merge_fetched_summary(store, detail.summary)
        store.put_detail(detail)
        self.rebuild_backups.pop(scope, None)
        self.dependency_links[key] = tuple(relation.target for relation in detail.relationships)
        self._hydrate(store)
        self._save_issue_store(scope)
        return detail, None
