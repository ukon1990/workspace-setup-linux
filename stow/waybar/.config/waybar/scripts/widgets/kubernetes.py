"""Waybar presentation for kubectl pod and workload readiness."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .common import classes, icon
from .tooltip import attention, esc, header, hint, render, table

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


K8S_ICON = icon("󰠳")


def _bar_text(status: dict) -> str:
    if not status.get("available"):
        return f"{K8S_ICON} n/a"
    pods = status.get("pods") or {}
    attention_count = int(pods.get("attention") or 0)
    text = f"{K8S_ICON} {pods.get('ready', 0)}/{pods.get('active', 0)} pods"
    if attention_count:
        text += "  " + attention(f"● {attention_count} not ready")
    return text


def _tooltip(status: dict) -> list[str]:
    facts = [("Context", esc(status.get("context") or "(unknown)"))]
    if status.get("namespace_filter"):
        facts.append(("Namespace", esc(status["namespace_filter"])))

    if not status.get("available"):
        errors = status.get("errors") or ["no cluster data"]
        return [header("KUBERNETES", "Unavailable"), *table(facts), *(esc(e) for e in errors)]

    pods = status.get("pods") or {}
    workloads = status.get("workloads") or {}
    lines = [
        header(
            "KUBERNETES",
            f"{pods.get('ready', 0)}/{pods.get('active', 0)} pods · "
            f"{workloads.get('ready', 0)}/{workloads.get('total', 0)} workloads",
        ),
        *table(facts),
    ]
    if status.get("partial"):
        lines.append(attention("Partial results; some resource queries failed"))
        lines.extend(esc(error) for error in status.get("errors") or [])

    # Problems first; healthy namespaces fold into the last line.
    namespaces = status.get("namespaces") or []
    troubled = [entry for entry in namespaces if entry.get("problems")]
    if troubled:
        lines += ["", attention("NEEDS ATTENTION")]
    for entry in troubled:
        npods = entry.get("pods") or {}
        problems = entry["problems"]
        lines.append(
            f"<tt><b>{esc(entry.get('name'))}</b>  "
            f"{npods.get('ready', 0)}/{npods.get('active', 0)} pods</tt>"
        )
        lines.extend(f"<tt>  {esc(_format_problem(p))}</tt>" for p in problems[:TOOLTIP_PROBLEM_LIMIT])
        if len(problems) > TOOLTIP_PROBLEM_LIMIT:
            lines.append(f"<tt>  …and {len(problems) - TOOLTIP_PROBLEM_LIMIT} more</tt>")
    healthy = len(namespaces) - len(troubled)
    lines += ["", hint(f"{healthy} healthy namespaces hidden · Click for full status")]
    return lines


def kubernetes_module(state):
    status = _load_status(state)
    if not status.get("available"):
        return {
            "text": _bar_text(status),
            **render(_tooltip(status)),
            "class": classes("metric", "muted"),
        }
    warning = bool(status.get("warning"))
    return {
        "text": _bar_text(status),
        **render(_tooltip(status)),
        "class": classes("metric", "warning" if warning else None),
    }
