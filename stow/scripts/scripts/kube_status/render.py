"""Terminal and structured JSON rendering for kube-status."""

from __future__ import annotations

import json
from typing import Any


def status_to_dict(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": status.get("context") or "",
        "namespace_filter": status.get("namespace_filter"),
        "available": bool(status.get("available")),
        "partial": bool(status.get("partial")),
        "errors": list(status.get("errors") or []),
        "pods": dict(status.get("pods") or {}),
        "workloads": dict(status.get("workloads") or {}),
        "warning": bool(status.get("warning")),
        "namespaces": list(status.get("namespaces") or []),
    }


def render_json(status: dict[str, Any]) -> str:
    return json.dumps(status_to_dict(status), indent=2, sort_keys=True)


def _format_problem(problem: dict[str, Any]) -> str:
    restarts = problem.get("restarts") or 0
    suffix = f", restarts={restarts}" if problem.get("kind") == "Pod" and restarts else ""
    return f"{problem['kind']}/{problem['name']}: {problem['reason']}{suffix}"


def render_terminal(status: dict[str, Any]) -> str:
    lines: list[str] = []
    context = status.get("context") or "(unknown)"
    namespace_filter = status.get("namespace_filter")
    scope = f"namespace {namespace_filter}" if namespace_filter else "all namespaces"
    lines.append(f"Context: {context} ({scope})")

    if not status.get("available"):
        lines.append("Status: unavailable")
        for error in status.get("errors") or []:
            lines.append(f"  error: {error}")
        if not status.get("errors"):
            lines.append("  error: no cluster data")
        return "\n".join(lines)

    pods = status.get("pods") or {}
    workloads = status.get("workloads") or {}
    lines.append(
        "Pods: "
        f"{pods.get('ready', 0)}/{pods.get('active', 0)} ready "
        f"(attention {pods.get('attention', 0)}, "
        f"completed {pods.get('completed', 0)}, "
        f"terminating {pods.get('terminating', 0)}, "
        f"restarts {pods.get('restarts', 0)})"
    )
    lines.append(
        "Workloads: "
        f"{workloads.get('ready', 0)}/{workloads.get('total', 0)} ready "
        f"(attention {workloads.get('attention', 0)}, "
        f"scaled down {workloads.get('scaled_down', 0)})"
    )
    if status.get("partial"):
        lines.append("Note: partial results; some resource queries failed")
        for error in status.get("errors") or []:
            lines.append(f"  error: {error}")

    namespaces = status.get("namespaces") or []
    if not namespaces:
        lines.append("")
        lines.append("No pods or workloads found.")
        return "\n".join(lines)

    for entry in namespaces:
        lines.append("")
        lines.append(f"Namespace: {entry['name']}")
        npods = entry.get("pods") or {}
        nwork = entry.get("workloads") or {}
        lines.append(
            "  Pods: "
            f"{npods.get('ready', 0)}/{npods.get('active', 0)} ready, "
            f"attention {npods.get('attention', 0)}, "
            f"completed {npods.get('completed', 0)}, "
            f"terminating {npods.get('terminating', 0)}, "
            f"restarts {npods.get('restarts', 0)}"
        )
        lines.append(
            "  Workloads: "
            f"{nwork.get('ready', 0)}/{nwork.get('total', 0)} ready, "
            f"attention {nwork.get('attention', 0)}, "
            f"scaled down {nwork.get('scaled_down', 0)}"
        )
        problems = entry.get("problems") or []
        if problems:
            lines.append("  Problems:")
            for problem in problems:
                lines.append(f"    - {_format_problem(problem)}")
        else:
            lines.append("  Problems: none")

    return "\n".join(lines)
