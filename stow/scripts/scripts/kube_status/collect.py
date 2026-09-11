"""Read-only kubectl collection for the current context."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from .common import REQUEST_TIMEOUT, SUBPROCESS_TIMEOUT, fail

RESOURCE_KINDS = (
    ("pods", "pods"),
    ("deployments", "deployments"),
    ("statefulsets", "statefulsets"),
    ("daemonsets", "daemonsets"),
)


def _completed(command: list[str], returncode: int, stdout: str, stderr: str):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def run_kubectl(args: list[str], *, kubectl: str = "kubectl") -> subprocess.CompletedProcess:
    command = [kubectl, *args]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except FileNotFoundError as exc:
        return _completed(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return _completed(command, 124, exc.stdout or "", exc.stderr or "timed out")


def resolve_context(explicit: str | None = None, *, kubectl: str = "kubectl") -> str:
    if explicit:
        return explicit
    result = run_kubectl(["config", "current-context"], kubectl=kubectl)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no current context").strip()
        fail(f"unable to resolve kubectl context: {detail}")
    context = result.stdout.strip()
    if not context:
        fail("unable to resolve kubectl context: empty current-context")
    return context


def _items(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def fetch_resources(
    context: str,
    *,
    namespace: str | None = None,
    kubectl: str = "kubectl",
) -> dict[str, Any]:
    """Fetch pods and workloads; keep successful results when a query fails."""
    if not shutil.which(kubectl) and kubectl == "kubectl":
        fail("kubectl is not installed or not on PATH")

    resources: dict[str, list[dict]] = {key: [] for key, _ in RESOURCE_KINDS}
    errors: list[str] = []
    succeeded = 0

    for key, resource in RESOURCE_KINDS:
        args = [
            "get",
            resource,
            "-o",
            "json",
            f"--context={context}",
            f"--request-timeout={REQUEST_TIMEOUT}",
        ]
        if namespace:
            args.extend(["-n", namespace])
        else:
            args.append("-A")

        result = run_kubectl(args, kubectl=kubectl)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
            errors.append(f"{resource}: {detail}")
            continue
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            errors.append(f"{resource}: invalid JSON ({exc})")
            continue
        resources[key] = _items(payload)
        succeeded += 1

    return {
        "context": context,
        "namespace": namespace,
        "resources": resources,
        "errors": errors,
        "partial": bool(errors) and succeeded > 0,
        "failed": succeeded == 0,
    }
