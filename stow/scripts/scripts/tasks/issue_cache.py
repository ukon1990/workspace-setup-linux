"""Scope-wide issue versions and bounded, persistent detail storage."""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import yaml

from .cache import (
    CacheError,
    _atomic_write,
    _decode_identity,
    _decode_summary,
    _encode_identity,
    _encode_summary,
    cache_path,
)
from .models import Comment, RelationshipKind, TaskDetail, TaskRelationship, TaskSummary

DETAIL_LIMIT = 200
FORMAT_VERSION = 2


def version_order(first, second):
    """Compare issue timestamps without differences in timezone spelling."""
    if first == second:
        return 0
    if first is None or second is None:
        return None
    try:

        def parse(value):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp

        left, right = parse(first), parse(second)
        return (left > right) - (left < right)
    except (TypeError, ValueError):
        return None


@dataclass
class IssueStore:
    synced_at: Optional[str] = None
    revision: int = 0
    items: dict[str, TaskSummary] = field(default_factory=dict)
    details: OrderedDict[str, TaskDetail] = field(default_factory=OrderedDict)

    def put_detail(self, detail: TaskDetail) -> None:
        key = detail.identity.stable_id
        self.items[key] = detail.summary
        self.details.pop(key, None)
        self.details[key] = detail
        while len(self.details) > DETAIL_LIMIT:
            self.details.popitem(last=False)


def store_path(scope, cache_dir=None):
    return cache_path(scope, cache_dir).with_suffix(".issues.yaml")


def load_store(scope, cache_dir=None) -> IssueStore:
    path = store_path(scope, cache_dir)
    if not path.exists():
        return IssueStore()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("format") != FORMAT_VERSION:
            return IssueStore()
        store = IssueStore(synced_at=raw.get("synced_at"), revision=raw.get("revision", 0))
        if store.synced_at is not None and not isinstance(store.synced_at, str):
            raise CacheError("invalid issue sync timestamp")
        if not isinstance(store.revision, int) or store.revision < 0:
            raise CacheError("invalid issue revision")
        for key, summary in raw.get("items", {}).items():
            try:
                task = _decode_summary(summary)
                if task.identity.stable_id == key:
                    store.items[key] = task
            except (CacheError, TypeError, AttributeError):
                continue
        for key, payload in raw.get("details", {}).items():
            try:
                detail = decode_detail(payload)
                summary = store.items.get(key)
                if (
                    summary is not None
                    and version_order(summary.updated_at, detail.summary.updated_at) == 0
                    and detail.identity.stable_id == key
                ):
                    store.details[key] = detail
            except (CacheError, ValueError, TypeError, KeyError, AttributeError):
                continue
        while len(store.details) > DETAIL_LIMIT:
            store.details.popitem(last=False)
        return store
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, AttributeError) as error:
        raise CacheError(f"Could not read issue cache {path}: {error}") from error


def save_store(scope, store, cache_dir=None):
    path = store_path(scope, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        path,
        {
            "format": FORMAT_VERSION,
            "synced_at": store.synced_at,
            "revision": store.revision,
            "items": {key: _encode_summary(task) for key, task in store.items.items()},
            "details": {key: encode_detail(detail) for key, detail in store.details.items()},
        },
    )


def encode_detail(detail):
    return {
        "summary": _encode_summary(detail.summary),
        "description": detail.description,
        "comments": [
            {
                "author": comment.author,
                "body": comment.body,
                "created_at": comment.created_at,
                "url": comment.url,
            }
            for comment in detail.comments
        ],
        "relationships": [
            {
                "kind": relation.kind.value,
                "target": _encode_identity(relation.target),
                "label": relation.label,
                "summary": relation.summary,
            }
            for relation in detail.relationships
        ],
    }


def decode_detail(raw):
    summary = _decode_summary(raw["summary"])
    return TaskDetail(
        summary,
        description=raw.get("description", ""),
        comments=tuple(Comment(**comment) for comment in raw.get("comments", [])),
        relationships=tuple(
            TaskRelationship(
                RelationshipKind(relation["kind"]),
                _decode_identity(relation["target"]),
                relation["label"],
                relation.get("summary"),
            )
            for relation in raw.get("relationships", [])
        ),
    )
