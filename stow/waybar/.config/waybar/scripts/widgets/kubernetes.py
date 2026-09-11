"""Waybar presentation for kubectl pod and workload readiness."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .common import classes

TOOLTIP_PROBLEM_LIMIT = 10
KUBE_STATUS = Path.home() / "scripts" / "kube-status.sh"
SUBPROCESS_TIMEOUT = 15


def _format_problem(problem: dict) -> str:
    restarts = problem.get("restarts") or 0
    suffix = f", restarts={restarts}" if problem.get("kind") == "Pod" and restarts else ""
    return f"{problem.get('kind')}/{problem.get('name')}: {problem.get('reason')}{suffix}"


def _load_status(state) -> dict:
    command = [str(KUBE_STATUS), "--json"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT,
        )
    except FileNotFoundError as exc:
        return {
            "available": False,
            "errors": [str(exc)],
            "context": "",
            "pods": {},
            "workloads": {},
            "namespaces": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "errors": ["kube-status timed out"],
            "context": "",
            "pods": {},
            "workloads": {},
            "namespaces": [],
        }

    if result.returncode not in (0, 1) or not (result.stdout or "").strip():
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        return {
            "available": False,
            "errors": [detail or "kube-status failed"],
            "context": "",
            "pods": {},
            "workloads": {},
            "namespaces": [],
        }

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "errors": [f"invalid JSON from kube-status: {exc}"],
            "context": "",
            "pods": {},
            "workloads": {},
            "namespaces": [],
        }
    if not isinstance(payload, dict):
        return {
            "available": False,
            "errors": ["invalid JSON from kube-status: expected object"],
            "context": "",
            "pods": {},
            "workloads": {},
            "namespaces": [],
        }
    state["kube_last"] = payload
    return payload


def _bar_text(status: dict) -> str:
    if not status.get("available"):
        return "󰠳 n/a"
    pods = status.get("pods") or {}
    workloads = status.get("workloads") or {}
    attention = int(pods.get("attention") or 0)
    text = (
        f"󰠳 P {pods.get('ready', 0)}/{pods.get('active', 0)} "
        f"W {workloads.get('ready', 0)}/{workloads.get('total', 0)}"
    )
    if attention:
        text += f" !{attention}"
    return text


def _tooltip(status: dict) -> str:
    context = status.get("context") or "(unknown)"
    lines = [f"Context: {context}"]
    if status.get("namespace_filter"):
        lines.append(f"Namespace filter: {status['namespace_filter']}")

    if not status.get("available"):
        lines.append("Status: unavailable")
        for error in status.get("errors") or ["no cluster data"]:
            lines.append(f"Error: {error}")
        return "\n".join(lines)

    pods = status.get("pods") or {}
    workloads = status.get("workloads") or {}
    lines.append(
        f"Pods: {pods.get('ready', 0)}/{pods.get('active', 0)} ready "
        f"(attention {pods.get('attention', 0)}, "
        f"completed {pods.get('completed', 0)}, "
        f"terminating {pods.get('terminating', 0)})"
    )
    lines.append(
        f"Workloads: {workloads.get('ready', 0)}/{workloads.get('total', 0)} ready "
        f"(attention {workloads.get('attention', 0)}, "
        f"scaled down {workloads.get('scaled_down', 0)})"
    )
    if status.get("partial"):
        lines.append("Partial results; some resource queries failed")
        for error in status.get("errors") or []:
            lines.append(f"Error: {error}")

    for entry in status.get("namespaces") or []:
        lines.append("")
        lines.append(f"{entry.get('name')}:")
        npods = entry.get("pods") or {}
        nwork = entry.get("workloads") or {}
        lines.append(
            f"  Pods {npods.get('ready', 0)}/{npods.get('active', 0)} "
            f"| Workloads {nwork.get('ready', 0)}/{nwork.get('total', 0)} "
            f"| Restarts {npods.get('restarts', 0)}"
        )
        problems = entry.get("problems") or []
        if not problems:
            lines.append("  Problems: none")
            continue
        shown = problems[:TOOLTIP_PROBLEM_LIMIT]
        omitted = len(problems) - len(shown)
        lines.append("  Problems:")
        for problem in shown:
            lines.append(f"    - {_format_problem(problem)}")
        if omitted:
            lines.append(f"    - …and {omitted} more")

    return "\n".join(lines)


def kubernetes_module(state):
    status = _load_status(state)
    if not status.get("available"):
        return {
            "text": _bar_text(status),
            "tooltip": _tooltip(status),
            "class": classes("metric", "muted"),
        }
    warning = bool(status.get("warning"))
    return {
        "text": _bar_text(status),
        "tooltip": _tooltip(status),
        "class": classes("metric", "warning" if warning else None),
    }
