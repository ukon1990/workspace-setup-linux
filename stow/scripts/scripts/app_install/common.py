"""Shared identifier validation and atomic file writes."""

import os
import re
import shlex
import tempfile
from pathlib import Path
from typing import NoReturn

PASSWORD_STORES = (
    "gnome-libsecret",
    "gnome",
    "kwallet5",
    "kwallet6",
    "kwallet",
    "basic",
)


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def identifier(name):
    value = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip(".-")
    if not value:
        fail("Name must contain letters or numbers.")
    return value


def normalize_password_store(value):
    """Validate a Chromium/Electron password-store backend, or None if cleared."""
    if value is None or value == "":
        return None
    if value not in PASSWORD_STORES:
        fail(
            "Unsupported --password-store "
            f"{value!r}; expected one of: {', '.join(PASSWORD_STORES)}."
        )
    return value


def resolve_password_store(cli_value, existing=None):
    """CLI value wins; omit keeps existing; empty string clears."""
    if cli_value is None:
        store = (existing or {}).get("password_store")
        return normalize_password_store(store) if store else None
    return normalize_password_store(cli_value)


def wrapper_script(launcher_path, kind, password_store=None):
    command = shlex.quote(str(launcher_path))
    if kind == "appimage":
        command += " --appimage-extract-and-run"
    if password_store:
        command += " --password-store=" + shlex.quote(password_store)
    return "#!/usr/bin/env bash\nset -euo pipefail\nexec " + command + ' "$@"\n'


def replace_file(path, content, mode=0o644):
    # os.replace replaces a symlink itself, never the file it points to.
    descriptor, temporary = tempfile.mkstemp(prefix=".app-install-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
