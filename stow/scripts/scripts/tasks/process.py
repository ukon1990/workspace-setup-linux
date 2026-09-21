"""Safe subprocess boundaries for backend command-line clients."""

import json
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

_SECRET_RE = re.compile(
    r"(?i)(authorization:\s*(?:bearer|basic)\s+|token[=:]\s*|password[=:]\s*)\S+"
)


class ProcessErrorKind(str, Enum):
    INVALID_COMMAND = "invalid_command"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    FAILED = "failed"
    INVALID_JSON = "invalid_json"


@dataclass
class ProcessError(RuntimeError):
    kind: ProcessErrorKind
    executable: str
    message: str
    returncode: Optional[int] = None

    def __str__(self) -> str:
        return self.message


def run_text(
    argv: Sequence[str],
    *,
    timeout: float = 30,
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Mapping[str, str]] = None,
    input_text: Optional[str] = None,
) -> str:
    command = _validate_command(argv)
    if isinstance(timeout, bool) or not isinstance(timeout, Real) or timeout <= 0:
        raise ProcessError(
            ProcessErrorKind.INVALID_COMMAND,
            command[0],
            "Command timeout must be greater than zero",
        )

    try:
        result = subprocess.run(
            command,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
            input=input_text,
        )
    except FileNotFoundError as error:
        raise ProcessError(
            ProcessErrorKind.NOT_FOUND,
            command[0],
            f"Required command not found: {command[0]}",
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ProcessError(
            ProcessErrorKind.TIMEOUT,
            command[0],
            f"{command[0]} timed out after {timeout:g} seconds",
        ) from error
    except OSError as error:
        raise ProcessError(
            ProcessErrorKind.FAILED,
            command[0],
            f"Could not run {command[0]}: {_redact(str(error))}",
        ) from error

    if result.returncode:
        detail = _redact((result.stderr or result.stdout).strip())
        message = f"{command[0]} exited with status {result.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise ProcessError(
            ProcessErrorKind.FAILED,
            command[0],
            message,
            result.returncode,
        )
    return result.stdout


def run_json(
    argv: Sequence[str],
    *,
    timeout: float = 30,
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Mapping[str, str]] = None,
    input_text: Optional[str] = None,
) -> Any:
    output = run_text(
        argv, timeout=timeout, cwd=cwd, env=env, input_text=input_text
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        executable = _validate_command(argv)[0]
        raise ProcessError(
            ProcessErrorKind.INVALID_JSON,
            executable,
            f"{executable} returned invalid JSON: {error.msg}",
        ) from error


def _validate_command(argv: Sequence[str]) -> list:
    if isinstance(argv, (str, bytes)) or not argv:
        raise ProcessError(
            ProcessErrorKind.INVALID_COMMAND,
            "",
            "Command must be a non-empty argument sequence",
        )
    if any(not isinstance(argument, str) or "\0" in argument for argument in argv):
        raise ProcessError(
            ProcessErrorKind.INVALID_COMMAND,
            "",
            "Command arguments must be strings without null bytes",
        )
    return list(argv)


def _redact(value: str) -> str:
    return _SECRET_RE.sub(r"\1[REDACTED]", value)
