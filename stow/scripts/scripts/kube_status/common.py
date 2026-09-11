"""Shared constants and helpers for kube-status."""

from typing import NoReturn

# kubectl --request-timeout; subprocess wait allows a little overhead.
REQUEST_TIMEOUT = "8s"
SUBPROCESS_TIMEOUT = 12


def fail(message: str) -> NoReturn:
    raise ValueError(message)
