"""Entrypoint invoked through sudo with the isolated system Python interpreter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if os.geteuid() != 0 or not os.environ.get("SUDO_UID"):
        print(
            "Run disks.sh as a normal user; this helper is only called through sudo.",
            file=sys.stderr,
        )
        return 1
    # -I removes CWD/PYTHONPATH; import only from this checkout, not the user's venv.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from disks.operations import execute

    try:
        request = json.load(sys.stdin)
        print(execute(request, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
