"""Unprivileged client of the explicitly sudo-authorized helper."""

import json
import subprocess
from pathlib import Path


def execute(request: dict) -> str:
    result = subprocess.run(["sudo", "-v"], check=False)
    if result.returncode:
        raise RuntimeError("Sudo authentication was cancelled or failed; no operation performed.")
    helper = Path(__file__).with_name("helper.py").resolve()
    result = subprocess.run(
        ["sudo", "-n", "--", "/usr/bin/python3", "-I", "-B", str(helper)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Disk operation failed.")
    return result.stdout.strip()
