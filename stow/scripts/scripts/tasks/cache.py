"""Disk cache for task list summaries with incremental sync timestamps."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import yaml

from .filters import AssigneeFilter
from .models import Backend, BackendIdentity, TaskSummary

DEFAULT_CACHE_DIR = Path("~/.local/state/tasks/cache")
_SCOPE_RE = re.compile(r"^(jira:[A-Z][A-Z0-9_]*|github:[^/:\s]+/[^/:\s]+)$")
_DETAIL_CAP = 200


class CacheError(ValueError):
    """Task cache could not be read or written."""


@dataclass
class CacheEntry:
    synced_at: str
    query: Optional[str]
    assignee: AssigneeFilter
    items: dict[str, TaskSummary] = field(default_factory=dict)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)

    def merge_items(self, tasks: Sequence[TaskSummary]) -> None:
        for task in tasks:
            self.items[task.identity.stable_id] = task

    def replace_items(self, tasks: Sequence[TaskSummary]) -> None:
        self.items = {task.identity.stable_id: task for task in tasks}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_github_since(synced_at: str) -> str:
    """GitHub search accepts YYYY-MM-DD (day precision is enough for deltas)."""
    return synced_at[:10]


def format_jira_since(synced_at: str) -> str:
    """Jira JQL updated >= \"yyyy-MM-dd HH:mm\" in UTC-ish wall time from ISO."""
    stamp = synced_at.replace("T", " ")
    if len(stamp) >= 16:
        return stamp[:16]
    return stamp[:10] + " 00:00"


def cache_path(scope: str, cache_dir: Optional[Union[str, Path]] = None) -> Path:
    _validate_scope(scope)
    root = Path(cache_dir or DEFAULT_CACHE_DIR).expanduser()
    safe = scope.replace(":", "-").replace("/", "-")
    return root / f"{safe}.yaml"


def load_entry(
    scope: str,
    query: Optional[str],
    assignee: AssigneeFilter,
    *,
    cache_dir: Optional[Union[str, Path]] = None,
) -> Optional[CacheEntry]:
    path = cache_path(scope, cache_dir)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise CacheError(f"Could not read task cache {path}: {error}") from error
    if not isinstance(raw, dict):
        return None
    scopes = raw.get("scopes")
    if not isinstance(scopes, dict):
        return None
    slot_key = _slot_key(query, assignee)
    payload = scopes.get(slot_key)
    if not isinstance(payload, dict):
        return None
    try:
        return _decode_entry(payload)
    except CacheError:
        return None


def save_entry(
    scope: str,
    entry: CacheEntry,
    *,
    cache_dir: Optional[Union[str, Path]] = None,
) -> None:
    path = cache_path(scope, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {"scopes": {}}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
            if isinstance(loaded, dict) and isinstance(loaded.get("scopes"), dict):
                existing = loaded
        except (OSError, UnicodeError, yaml.YAMLError):
            existing = {"scopes": {}}
    scopes = existing.setdefault("scopes", {})
    if not isinstance(scopes, dict):
        scopes = {}
        existing["scopes"] = scopes
    scopes[_slot_key(entry.query, entry.assignee)] = _encode_entry(entry)
    _atomic_write(path, existing)


def _slot_key(query: Optional[str], assignee: AssigneeFilter) -> str:
    normalized = (query or "open").strip() or "open"
    return f"{normalized}|{assignee.value}"


def _validate_scope(scope: str) -> None:
    if not isinstance(scope, str) or not _SCOPE_RE.fullmatch(scope):
        raise CacheError("scope must use jira:PROJECT or github:owner/repository format")


def _encode_entry(entry: CacheEntry) -> dict[str, Any]:
    return {
        "synced_at": entry.synced_at,
        "query": entry.query,
        "assignee": entry.assignee.value,
        "items": {
            stable_id: _encode_summary(task) for stable_id, task in sorted(entry.items.items())
        },
        "details": dict(list(entry.details.items())[-_DETAIL_CAP:]),
    }


def _decode_entry(payload: Mapping[str, Any]) -> CacheEntry:
    synced_at = payload.get("synced_at")
    if not isinstance(synced_at, str) or not synced_at.strip():
        raise CacheError("cache entry missing synced_at")
    assignee_raw = payload.get("assignee", AssigneeFilter.ALL.value)
    try:
        assignee = AssigneeFilter(assignee_raw)
    except (TypeError, ValueError) as error:
        raise CacheError("cache entry has invalid assignee") from error
    query = payload.get("query")
    if query is not None and not isinstance(query, str):
        raise CacheError("cache entry query must be a string or null")
    raw_items = payload.get("items") or {}
    if not isinstance(raw_items, dict):
        raise CacheError("cache entry items must be a mapping")
    items = {}
    for stable_id, raw in raw_items.items():
        if not isinstance(stable_id, str) or not isinstance(raw, dict):
            continue
        try:
            items[stable_id] = _decode_summary(raw)
        except CacheError:
            continue
    raw_details = payload.get("details") or {}
    details = raw_details if isinstance(raw_details, dict) else {}
    return CacheEntry(
        synced_at=synced_at,
        query=query,
        assignee=assignee,
        items=items,
        details={key: value for key, value in details.items() if isinstance(key, str)},
    )


def _encode_identity(identity: BackendIdentity) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "backend": identity.backend.value,
        "key": identity.key,
    }
    if identity.repository:
        payload["repository"] = identity.repository
    if identity.url:
        payload["url"] = identity.url
    return payload


def _decode_identity(payload: Mapping[str, Any]) -> BackendIdentity:
    backend_raw = payload.get("backend")
    key = payload.get("key")
    if not isinstance(backend_raw, str) or not isinstance(key, str):
        raise CacheError("invalid identity")
    try:
        backend = Backend(backend_raw)
    except ValueError as error:
        raise CacheError("invalid identity backend") from error
    repository = payload.get("repository")
    url = payload.get("url")
    if repository is not None and not isinstance(repository, str):
        raise CacheError("invalid identity repository")
    if url is not None and not isinstance(url, str):
        raise CacheError("invalid identity url")
    return BackendIdentity(backend, key, repository=repository, url=url)


def _encode_summary(task: TaskSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "identity": _encode_identity(task.identity),
        "title": task.title,
        "status": task.status,
        "assignees": list(task.assignees),
        "labels": list(task.labels),
        "components": list(task.components),
    }
    if task.task_type:
        payload["task_type"] = task.task_type
    if task.priority:
        payload["priority"] = task.priority
    if task.url:
        payload["url"] = task.url
    if task.parent is not None:
        payload["parent"] = _encode_identity(task.parent)
    return payload


def _decode_summary(payload: Mapping[str, Any]) -> TaskSummary:
    identity_raw = payload.get("identity")
    if not isinstance(identity_raw, dict):
        raise CacheError("summary missing identity")
    title = payload.get("title")
    status = payload.get("status")
    if not isinstance(title, str) or not isinstance(status, str):
        raise CacheError("summary missing title/status")
    parent = None
    parent_raw = payload.get("parent")
    if isinstance(parent_raw, dict):
        parent = _decode_identity(parent_raw)
    return TaskSummary(
        identity=_decode_identity(identity_raw),
        title=title,
        status=status,
        task_type=payload.get("task_type") if isinstance(payload.get("task_type"), str) else None,
        priority=payload.get("priority") if isinstance(payload.get("priority"), str) else None,
        assignees=tuple(payload.get("assignees") or ()),
        labels=tuple(payload.get("labels") or ()),
        components=tuple(payload.get("components") or ()),
        url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        parent=parent,
    )


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            yaml.safe_dump(dict(payload), handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise CacheError(f"Could not write task cache {path}: {error}") from error
