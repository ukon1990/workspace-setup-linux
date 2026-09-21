"""Local looked-at state for PR file review tracking."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml

DEFAULT_REVIEW_VIEWS_PATH = Path("~/.local/state/tasks/review-views.yaml")


def hunk_fingerprint(hunk: str) -> str:
    return hashlib.sha256(hunk.encode("utf-8")).hexdigest()[:16]


def review_views_path(path: Optional[Union[str, Path]] = None) -> Path:
    return Path(path or DEFAULT_REVIEW_VIEWS_PATH).expanduser()


def load_viewed_files(
    pull_stable_id: str, *, path: Optional[Union[str, Path]] = None
) -> dict[str, str]:
    root = _load_root(path)
    entry = root.get(pull_stable_id)
    if not isinstance(entry, dict):
        return {}
    files = entry.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in files.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def mark_file_viewed(
    pull_stable_id: str,
    file_path: str,
    fingerprint: str,
    *,
    path: Optional[Union[str, Path]] = None,
) -> None:
    root = _load_root(path)
    entry = root.setdefault(pull_stable_id, {})
    if not isinstance(entry, dict):
        entry = {}
        root[pull_stable_id] = entry
    files = entry.setdefault("files", {})
    if not isinstance(files, dict):
        files = {}
        entry["files"] = files
    files[file_path] = fingerprint
    _write_root(root, path)


def file_view_status(
    pull_stable_id: str,
    file_path: str,
    fingerprint: str,
    *,
    path: Optional[Union[str, Path]] = None,
) -> str:
    """Return ``new``, ``viewed``, or ``stale``."""
    viewed = load_viewed_files(pull_stable_id, path=path)
    previous = viewed.get(file_path)
    if previous is None:
        return "new"
    if previous == fingerprint:
        return "viewed"
    return "stale"


def _load_root(path: Optional[Union[str, Path]]) -> dict[str, Any]:
    target = review_views_path(path)
    if not target.exists():
        return {}
    try:
        with target.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    views = raw.get("views")
    return dict(views) if isinstance(views, dict) else {}


def _write_root(views: Mapping[str, Any], path: Optional[Union[str, Path]]) -> None:
    target = review_views_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"views": dict(views)}
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        dir=str(target.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=True)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
