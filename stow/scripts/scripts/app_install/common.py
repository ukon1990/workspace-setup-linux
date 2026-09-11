"""Shared identifier validation and atomic file writes."""

import os
import re
import tempfile
from pathlib import Path
from typing import NoReturn


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def identifier(name):
    value = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip(".-")
    if not value:
        fail("Name must contain letters or numbers.")
    return value


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
