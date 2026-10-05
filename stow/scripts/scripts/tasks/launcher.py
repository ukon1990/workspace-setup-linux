"""Minimal persisted backend choice for the startup menu."""

import os
import tempfile
from pathlib import Path

import yaml

from .models import Backend

DEFAULT_LAUNCHER_PATH = Path("~/.local/state/tasks/launcher.yaml")


def load_recent_backend(path=None) -> Backend:
    """Missing or invalid state uses the first-launch GitHub default."""
    try:
        raw = yaml.safe_load(
            Path(path or DEFAULT_LAUNCHER_PATH).expanduser().read_text(encoding="utf-8")
        )
        if not isinstance(raw, dict) or set(raw) != {"backend"}:
            return Backend.GITHUB
        return Backend(raw["backend"])
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError):
        return Backend.GITHUB


def save_recent_backend(backend: Backend, path=None) -> None:
    """Atomically remember only the backend, with private file permissions."""
    state_path = Path(path or DEFAULT_LAUNCHER_PATH).expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=state_path.parent, prefix=".launcher-", delete=False
        ) as state_file:
            temporary_path = Path(state_file.name)
            yaml.safe_dump({"backend": Backend(backend).value}, state_file)
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary_path, state_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
