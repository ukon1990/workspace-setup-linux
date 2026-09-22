"""Last-viewed timestamps for pull requests opened in the TUI."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import yaml

DEFAULT_PR_VIEWS_PATH = Path("~/.local/state/tasks/pr-views.yaml")


def pr_views_path(path: Optional[Union[str, Path]] = None) -> Path:
    return Path(path or DEFAULT_PR_VIEWS_PATH).expanduser()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def load_pr_viewed_at(
    pull_stable_id: str, *, path: Optional[Union[str, Path]] = None
) -> Optional[str]:
    entry = _load_root(path).get(pull_stable_id)
    if not isinstance(entry, dict):
        return None
    viewed_at = entry.get("viewed_at")
    return viewed_at if isinstance(viewed_at, str) and viewed_at.strip() else None


def mark_pr_viewed(
    pull_stable_id: str,
    *,
    viewed_at: Optional[str] = None,
    path: Optional[Union[str, Path]] = None,
) -> str:
    stamp = viewed_at or utc_now_iso()
    root = _load_root(path)
    entry = root.setdefault(pull_stable_id, {})
    if not isinstance(entry, dict):
        entry = {}
        root[pull_stable_id] = entry
    entry["viewed_at"] = stamp
    _write_root(root, path)
    return stamp


def activity_label(updated_at: Optional[str], viewed_at: Optional[str]) -> str:
    """List marker: never viewed, changed since view, or caught up."""
    if viewed_at is None:
        return "·"
    if updated_at and updated_at > viewed_at:
        return "*"
    return "-"


def _load_root(path: Optional[Union[str, Path]]) -> dict[str, Any]:
    target = pr_views_path(path)
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
    target = pr_views_path(path)
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
