"""Persisted structured filters for the tasks browser."""

import fcntl
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Union

import yaml

DEFAULT_FILTERS_PATH = Path("~/.local/state/tasks/filters.yaml")
_JIRA_SCOPE_RE = re.compile(r"^jira:[A-Z][A-Z0-9_]*$")
_GITHUB_SCOPE_RE = re.compile(r"^github:[^/:\s]+/[^/:\s]+$")


class AssigneeFilter(str, Enum):
    ALL = "all"
    ME = "me"
    UNASSIGNED = "unassigned"
    ME_OR_UNASSIGNED = "me_or_unassigned"
    ASSIGNED_ANYONE = "assigned_anyone"

    @property
    def label(self) -> str:
        return {
            self.ALL: "All",
            self.ME: "Assigned to me",
            self.UNASSIGNED: "Unassigned",
            self.ME_OR_UNASSIGNED: "Me or unassigned",
            self.ASSIGNED_ANYONE: "Assigned to anyone",
        }[self]


class WorkFilter(str, Enum):
    ALL = "all"
    AVAILABLE = "available"
    READY_ONLY = "ready_only"

    @property
    def label(self) -> str:
        return {self.ALL: "All", self.AVAILABLE: "Available", self.READY_ONLY: "Ready only"}[self]


class FilterStateError(ValueError):
    """Filter state could not be validated or safely changed."""


@dataclass(frozen=True)
class FilterLoadResult:
    selection: AssigneeFilter = AssigneeFilter.ALL
    warning: Optional[str] = None


@dataclass(frozen=True)
class WorkFilterLoadResult:
    selection: WorkFilter = WorkFilter.ALL
    warning: Optional[str] = None


def load_assignee_filter(scope: str, path: Optional[Union[str, Path]] = None) -> FilterLoadResult:
    return _load_filter(scope, "assignee", FilterLoadResult, path)


def load_work_filter(scope: str, path: Optional[Union[str, Path]] = None) -> WorkFilterLoadResult:
    return _load_filter(scope, "work", WorkFilterLoadResult, path)


def _load_filter(scope, field, result_type, path):
    _validate_scope(scope)
    state_path = _state_path(path)
    if not state_path.exists():
        return result_type()
    try:
        scopes = _read_scopes(state_path)
    except FilterStateError as error:
        return result_type(warning=str(error))
    return result_type(selection=scopes.get(scope, _defaults())[field])


def save_assignee_filter(
    scope: str,
    selection: Union[AssigneeFilter, str],
    path: Optional[Union[str, Path]] = None,
) -> None:
    _save_filter(scope, "assignee", _selection(selection), path)


def save_work_filter(
    scope: str,
    selection: Union[WorkFilter, str],
    path: Optional[Union[str, Path]] = None,
) -> None:
    _save_filter(scope, "work", _work_selection(selection), path)


def clear_assignee_filter(scope: str, path: Optional[Union[str, Path]] = None) -> None:
    _save_filter(scope, "assignee", AssigneeFilter.ALL, path)


def clear_work_filter(scope: str, path: Optional[Union[str, Path]] = None) -> None:
    _save_filter(scope, "work", WorkFilter.ALL, path)


def _defaults() -> dict:
    return {"assignee": AssigneeFilter.ALL, "work": WorkFilter.ALL}


def _save_filter(scope, field, selected, path):
    """Update one filter atomically, preserving the other filter and scopes."""
    _validate_scope(scope)
    state_path = _state_path(path)
    with _state_lock(state_path):
        scopes = _read_scopes(state_path) if state_path.exists() else {}
        entry = dict(scopes.get(scope, _defaults()))
        entry[field] = selected
        if entry == _defaults():
            scopes.pop(scope, None)
        else:
            scopes[scope] = entry
        if scopes:
            _write_scopes(state_path, scopes)
        elif state_path.exists():
            state_path.unlink()


def _state_path(path: Optional[Union[str, Path]]) -> Path:
    return Path(path or DEFAULT_FILTERS_PATH).expanduser()


def _validate_scope(scope: str) -> None:
    if not isinstance(scope, str) or not (
        _JIRA_SCOPE_RE.fullmatch(scope) or _GITHUB_SCOPE_RE.fullmatch(scope)
    ):
        raise FilterStateError("scope must use jira:PROJECT or github:owner/repository format")


def _selection(value: Union[AssigneeFilter, str]) -> AssigneeFilter:
    try:
        return AssigneeFilter(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(option.value for option in AssigneeFilter)
        raise FilterStateError(f"assignee filter must be one of: {allowed}") from error


def _work_selection(value: Union[WorkFilter, str]) -> WorkFilter:
    try:
        return WorkFilter(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(option.value for option in WorkFilter)
        raise FilterStateError(f"work filter must be one of: {allowed}") from error


def _read_scopes(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as state_file:
            raw = yaml.safe_load(state_file)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise FilterStateError(f"Could not read filter state {path}: {error}") from error

    root = _mapping(raw, "filter state")
    if set(root) != {"scopes"}:
        raise FilterStateError("filter state must contain only a scopes mapping")
    raw_scopes = _mapping(root["scopes"], "filter state scopes")

    scopes = {}
    for scope, raw_filter in raw_scopes.items():
        _validate_scope(scope)
        entry = _mapping(raw_filter, f"filter state scope {scope}")
        if not entry or not set(entry) <= {"assignee", "work"}:
            raise FilterStateError(f"filter state scope {scope} must contain assignee or work")
        scopes[scope] = {
            "assignee": _selection(entry.get("assignee", AssigneeFilter.ALL)),
            "work": _work_selection(entry.get("work", WorkFilter.ALL)),
        }
    return scopes


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FilterStateError(f"{name} must be a mapping with string keys")
    return value


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    try:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError as error:
        raise FilterStateError(f"Could not lock filter state {path}: {error}") from error


def _write_scopes(path: Path, scopes: Mapping[str, Mapping[str, Enum]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scopes": {
            scope: {field: value.value for field, value in entry.items()}
            for scope, entry in sorted(scopes.items())
        }
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as state_file:
            temporary_path = Path(state_file.name)
            yaml.safe_dump(payload, state_file, sort_keys=False)
            state_file.flush()
            os.fsync(state_file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise FilterStateError(f"Could not write filter state {path}: {error}") from error
