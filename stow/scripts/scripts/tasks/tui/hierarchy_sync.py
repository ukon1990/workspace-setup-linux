"""Reconcile cached child inventories without refetching unchanged parents."""

from contextlib import contextmanager
from dataclasses import replace

from ..issue_cache import version_order
from ..models import RelationshipKind, TaskRelationship


class HierarchySync:
    @contextmanager
    def batch_hierarchy(self):
        """Persist affected parent scopes once after reconciling a batch."""
        self._hierarchy_scopes = set()
        try:
            yield
        finally:
            scopes = self._hierarchy_scopes
            self._hierarchy_scopes = None
            for scope in scopes:
                self._save_issue_store(scope)

    def remember_hierarchy_summary(self, task):
        key = task.identity.stable_id
        old = self.cached_items.get(key)
        if old is not None and version_order(task.updated_at, old.updated_at) == 0:
            if old.children_complete and not task.children_complete:
                task = replace(task, children=old.children, children_complete=True)
        if self.persistent_sync:
            scope = self.scope_for_identity(task.identity)
            store = self._issue_store(scope)
            self._merge_fetched_summary(store, task)
            task = store.items.get(key, task)
        self.cached_items[key] = task
        self.reconcile_hierarchy(task, old)
        return self.cached_items[key]

    def reconcile_hierarchy(self, task, old=None):
        if not task.dependencies_complete:
            return
        key = task.identity.stable_id
        parents = {
            parent.identity.stable_id: parent
            for parent in self.cached_items.values()
            if any(child.stable_id == key for child in parent.children)
        }
        if old is not None and old.parent is not None:
            parent = self.cached_items.get(old.parent.stable_id)
            if parent is not None:
                parents[parent.identity.stable_id] = parent
        if task.parent is not None:
            parent = self.cached_items.get(task.parent.stable_id)
            if parent is not None:
                parents[parent.identity.stable_id] = parent
        for parent_key, parent in parents.items():
            children = {
                child.stable_id: child for child in parent.children if child.stable_id != key
            }
            if task.parent is not None and parent_key == task.parent.stable_id:
                children[key] = task.identity
            if set(children) == {child.stable_id for child in parent.children}:
                continue
            updated = replace(parent, children=tuple(children.values()))
            self.cached_items[parent_key] = updated
            if self.persistent_sync:
                scope = self.scope_for_identity(parent.identity)
                self._issue_store(scope).items[parent_key] = updated
                scopes = getattr(self, "_hierarchy_scopes", None)
                if scopes is None:
                    self._save_issue_store(scope)
                else:
                    scopes.add(scope)

    def hierarchy_detail(self, detail):
        summary = self.cached_items.get(detail.identity.stable_id, detail.summary)
        children = {identity.stable_id: identity for identity in summary.children}
        children.update(
            (task.identity.stable_id, task.identity)
            for task in self.cached_items.values()
            if task.parent is not None and task.parent.stable_id == summary.identity.stable_id
        )
        relations = []
        for relation in detail.relationships:
            if relation.kind is not RelationshipKind.CHILD:
                relations.append(relation)
            elif relation.target.stable_id in children or not summary.children_complete:
                relations.append(relation)
                children.pop(relation.target.stable_id, None)
        for key, identity in children.items():
            task = self.cached_items.get(key)
            relations.append(
                TaskRelationship(
                    RelationshipKind.CHILD,
                    identity,
                    "sub-issue",
                    task.title if task is not None else None,
                )
            )
        return replace(detail, summary=summary, relationships=tuple(relations))
