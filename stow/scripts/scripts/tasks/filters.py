"""Persisted structured filters for the tasks browser."""

import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Union

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


class FilterStateError(ValueError):
    """Filter state could not be validated or safely changed."""


@dataclass(frozen=True)
class FilterLoadResult:
    selection: AssigneeFilter = AssigneeFilter.ALL
    warning: Optional[str] = None


def load_assignee_filter(scope: str, path: Optional[Union[str, Path]] = None) -> FilterLoadResult:
    """Load one scope, falling back to ALL with a warning for invalid state."""
    _validate_scope(scope)
    state_path = _state_path(path)
    if not state_path.exists():
        return FilterLoadResult()

    try:
        scopes = _read_scopes(state_path)
    except FilterStateError as error:
        return FilterLoadResult(warning=str(error))

    return FilterLoadResult(selection=scopes.get(scope, AssigneeFilter.ALL))


def save_assignee_filter(
    scope: str,
    selection: Union[AssigneeFilter, str],
    path: Optional[Union[str, Path]] = None,
) -> None:
    """Atomically save one scope while preserving all other scopes."""
    _validate_scope(scope)
    selected = _selection(selection)
    state_path = _state_path(path)
    scopes = _read_scopes(state_path) if state_path.exists() else {}
    scopes[scope] = selected
    _write_scopes(state_path, scopes)


def clear_assignee_filter(scope: str, path: Optional[Union[str, Path]] = None) -> None:
    """Remove one scope while preserving all other scopes."""
    _validate_scope(scope)
    state_path = _state_path(path)
    if not state_path.exists():
        return

    scopes = _read_scopes(state_path)
    if scope not in scopes:
        return
    del scopes[scope]
    if scopes:
        _write_scopes(state_path, scopes)
    else:
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
        if set(entry) != {"assignee"}:
            raise FilterStateError(f"filter state scope {scope} must contain only assignee")
        scopes[scope] = _selection(entry["assignee"])
    return scopes


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FilterStateError(f"{name} must be a mapping with string keys")
    return value


def _write_scopes(path: Path, scopes: Mapping[str, AssigneeFilter]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scopes": {
            scope: {"assignee": selection.value} for scope, selection in sorted(scopes.items())
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
