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
from .models import Backend, BackendIdentity, CiState, PullSummary, TaskSummary

DEFAULT_CACHE_DIR = Path("~/.local/state/tasks/cache")
# Bump when summary fields required for overview change (forces full refetch).
CACHE_FORMAT_VERSION = 2
PULL_CACHE_FORMAT_VERSION = 1
_SCOPE_RE = re.compile(r"^(jira:[A-Z][A-Z0-9_]*|github:[^/:\s]+/[^/:\s]+)$")
_DETAIL_CAP = 200
_PULL_SLOT_PREFIX = "pulls|"


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


@dataclass
class PullCacheEntry:
    synced_at: str
    query: Optional[str]
    assignee: AssigneeFilter
    items: dict[str, PullSummary] = field(default_factory=dict)

    def merge_items(self, pulls: Sequence[PullSummary]) -> None:
        for pull in pulls:
            self.items[pull.stable_id] = pull

    def replace_items(self, pulls: Sequence[PullSummary]) -> None:
        self.items = {pull.stable_id: pull for pull in pulls}


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


def load_pull_entry(
    scope: str,
    query: Optional[str],
    assignee: AssigneeFilter,
    *,
    cache_dir: Optional[Union[str, Path]] = None,
) -> Optional[PullCacheEntry]:
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
    payload = scopes.get(_pull_slot_key(query, assignee))
    if not isinstance(payload, dict):
        return None
    try:
        return _decode_pull_entry(payload)
    except CacheError:
        return None


def save_pull_entry(
    scope: str,
    entry: PullCacheEntry,
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
    scopes[_pull_slot_key(entry.query, entry.assignee)] = _encode_pull_entry(entry)
    _atomic_write(path, existing)


def _slot_key(query: Optional[str], assignee: AssigneeFilter) -> str:
    normalized = (query or "open").strip() or "open"
    return f"{normalized}|{assignee.value}"


def _pull_slot_key(query: Optional[str], assignee: AssigneeFilter) -> str:
    return f"{_PULL_SLOT_PREFIX}{_slot_key(query, assignee)}"


def _validate_scope(scope: str) -> None:
    if not isinstance(scope, str) or not _SCOPE_RE.fullmatch(scope):
        raise CacheError("scope must use jira:PROJECT or github:owner/repository format")


def _encode_entry(entry: CacheEntry) -> dict[str, Any]:
    return {
        "format": CACHE_FORMAT_VERSION,
        "synced_at": entry.synced_at,
        "query": entry.query,
        "assignee": entry.assignee.value,
        "items": {
            stable_id: _encode_summary(task) for stable_id, task in sorted(entry.items.items())
        },
        "details": dict(list(entry.details.items())[-_DETAIL_CAP:]),
    }


def _decode_entry(payload: Mapping[str, Any]) -> CacheEntry:
    format_version = payload.get("format", 0)
    if not isinstance(format_version, int) or format_version < CACHE_FORMAT_VERSION:
        raise CacheError("cache entry format is outdated")
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
    if task.blocked_by:
        payload["blocked_by"] = [_encode_identity(item) for item in task.blocked_by]
    if task.blocks:
        payload["blocks"] = [_encode_identity(item) for item in task.blocks]
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
        blocked_by=_decode_identity_tuple(payload.get("blocked_by")),
        blocks=_decode_identity_tuple(payload.get("blocks")),
    )


def _decode_identity_tuple(value: Any) -> tuple[BackendIdentity, ...]:
    if not isinstance(value, list):
        return ()
    identities: list[BackendIdentity] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            identities.append(_decode_identity(item))
        except CacheError:
            continue
    return tuple(identities)


def _encode_pull_entry(entry: PullCacheEntry) -> dict[str, Any]:
    return {
        "format": PULL_CACHE_FORMAT_VERSION,
        "kind": "pulls",
        "synced_at": entry.synced_at,
        "query": entry.query,
        "assignee": entry.assignee.value,
        "items": {
            stable_id: _encode_pull_summary(pull)
            for stable_id, pull in sorted(entry.items.items())
        },
    }


def _decode_pull_entry(payload: Mapping[str, Any]) -> PullCacheEntry:
    format_version = payload.get("format", 0)
    if not isinstance(format_version, int) or format_version < PULL_CACHE_FORMAT_VERSION:
        raise CacheError("pull cache entry format is outdated")
    if payload.get("kind") != "pulls":
        raise CacheError("not a pull cache entry")
    synced_at = payload.get("synced_at")
    if not isinstance(synced_at, str) or not synced_at.strip():
        raise CacheError("pull cache entry missing synced_at")
    assignee_raw = payload.get("assignee", AssigneeFilter.ALL.value)
    try:
        assignee = AssigneeFilter(assignee_raw)
    except (TypeError, ValueError) as error:
        raise CacheError("pull cache entry has invalid assignee") from error
    query = payload.get("query")
    if query is not None and not isinstance(query, str):
        raise CacheError("pull cache entry query must be a string or null")
    raw_items = payload.get("items") or {}
    if not isinstance(raw_items, dict):
        raise CacheError("pull cache entry items must be a mapping")
    items: dict[str, PullSummary] = {}
    for stable_id, raw in raw_items.items():
        if not isinstance(stable_id, str) or not isinstance(raw, dict):
            continue
        try:
            items[stable_id] = _decode_pull_summary(raw)
        except CacheError:
            continue
    return PullCacheEntry(
        synced_at=synced_at,
        query=query,
        assignee=assignee,
        items=items,
    )


def _encode_pull_summary(pull: PullSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "repository": pull.repository,
        "number": pull.number,
        "title": pull.title,
        "status": pull.status,
        "author": pull.author,
        "assignees": list(pull.assignees),
        "labels": list(pull.labels),
        "is_draft": pull.is_draft,
        "ci_state": pull.ci_state.value,
    }
    if pull.url:
        payload["url"] = pull.url
    if pull.review_decision:
        payload["review_decision"] = pull.review_decision
    if pull.created_at:
        payload["created_at"] = pull.created_at
    if pull.updated_at:
        payload["updated_at"] = pull.updated_at
    return payload


def _decode_pull_summary(payload: Mapping[str, Any]) -> PullSummary:
    repository = payload.get("repository")
    number = payload.get("number")
    title = payload.get("title")
    status = payload.get("status")
    if (
        not isinstance(repository, str)
        or not isinstance(number, int)
        or not isinstance(title, str)
        or not isinstance(status, str)
    ):
        raise CacheError("invalid pull summary")
    ci_raw = payload.get("ci_state", CiState.UNKNOWN.value)
    try:
        ci_state = CiState(ci_raw) if isinstance(ci_raw, str) else CiState.UNKNOWN
    except ValueError:
        ci_state = CiState.UNKNOWN
    return PullSummary(
        repository=repository,
        number=number,
        title=title,
        status=status,
        author=payload.get("author") if isinstance(payload.get("author"), str) else "",
        assignees=tuple(payload.get("assignees") or ()),
        labels=tuple(payload.get("labels") or ()),
        url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        is_draft=bool(payload.get("is_draft")),
        ci_state=ci_state,
        review_decision=(
            payload.get("review_decision")
            if isinstance(payload.get("review_decision"), str)
            else None
        ),
        created_at=(
            payload.get("created_at") if isinstance(payload.get("created_at"), str) else None
        ),
        updated_at=(
            payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None
        ),
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
