"""Aggregate kubectl resources into pod/workload readiness status."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _meta(item: dict) -> tuple[str, str]:
    metadata = item.get("metadata") or {}
    return str(metadata.get("namespace") or ""), str(metadata.get("name") or "")


def _container_restarts(pod: dict) -> int:
    status = pod.get("status") or {}
    total = 0
    for key in ("containerStatuses", "initContainerStatuses"):
        for container in status.get(key) or []:
            if isinstance(container, dict):
                try:
                    total += int(container.get("restartCount") or 0)
                except (TypeError, ValueError):
                    continue
    return total


def _containers_ready(pod: dict) -> tuple[int, int]:
    status = pod.get("status") or {}
    containers = status.get("containerStatuses") or []
    if not containers:
        spec = pod.get("spec") or {}
        desired = len(spec.get("containers") or [])
        return 0, desired
    ready = sum(1 for c in containers if isinstance(c, dict) and c.get("ready"))
    return ready, len(containers)


def _pod_reason(pod: dict, phase: str, ready: int, desired: int) -> str:
    status = pod.get("status") or {}
    for container in status.get("containerStatuses") or []:
        if not isinstance(container, dict) or container.get("ready"):
            continue
        state = container.get("state") or {}
        for key in ("waiting", "terminated"):
            detail = state.get(key)
            if isinstance(detail, dict) and detail.get("reason"):
                return str(detail["reason"])
    if phase == "Running" and desired and ready < desired:
        return f"not ready ({ready}/{desired})"
    return phase or "Unknown"


def classify_pod(pod: dict) -> dict[str, Any]:
    namespace, name = _meta(pod)
    metadata = pod.get("metadata") or {}
    status = pod.get("status") or {}
    phase = str(status.get("phase") or "Unknown")
    deleting = bool(metadata.get("deletionTimestamp"))
    ready_count, desired = _containers_ready(pod)
    restarts = _container_restarts(pod)

    if deleting:
        category = "terminating"
    elif phase == "Succeeded":
        category = "completed"
    elif phase == "Failed":
        category = "attention"
    elif phase == "Pending":
        category = "attention"
    elif phase == "Unknown":
        category = "attention"
    elif phase == "Running" and desired > 0 and ready_count >= desired:
        category = "ready"
    elif phase == "Running":
        category = "attention"
    else:
        category = "attention"

    problem = None
    if category == "attention":
        problem = {
            "kind": "Pod",
            "name": name,
            "reason": _pod_reason(pod, phase, ready_count, desired),
            "restarts": restarts,
        }

    return {
        "namespace": namespace,
        "name": name,
        "category": category,
        "phase": phase,
        "restarts": restarts,
        "ready": ready_count,
        "desired": desired,
        "problem": problem,
    }


def _generation_current(item: dict) -> bool:
    metadata = item.get("metadata") or {}
    status = item.get("status") or {}
    try:
        generation = int(metadata.get("generation") or 0)
        observed = int(status.get("observedGeneration") or 0)
    except (TypeError, ValueError):
        return False
    if generation == 0 and observed == 0:
        return True
    return observed >= generation


def _replica_counts(item: dict, kind: str) -> tuple[int, int]:
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    if kind == "DaemonSet":
        desired = int(status.get("desiredNumberScheduled") or 0)
        ready = int(status.get("numberReady") or 0)
        return ready, desired
    desired = int(spec.get("replicas") if spec.get("replicas") is not None else 1)
    ready = int(status.get("readyReplicas") or 0)
    return ready, desired


def classify_workload(item: dict, kind: str) -> dict[str, Any]:
    namespace, name = _meta(item)
    ready, desired = _replica_counts(item, kind)
    current = _generation_current(item)

    if desired == 0:
        category = "scaled_down"
    elif current and ready >= desired:
        category = "ready"
    else:
        category = "attention"

    problem = None
    if category == "attention":
        reasons = []
        if not current:
            reasons.append("stale generation")
        reasons.append(f"{ready}/{desired} ready")
        problem = {
            "kind": kind,
            "name": name,
            "reason": ", ".join(reasons),
            "restarts": 0,
        }

    return {
        "namespace": namespace,
        "name": name,
        "kind": kind,
        "category": category,
        "ready": ready,
        "desired": desired,
        "problem": problem,
    }


def _empty_pod_counts() -> dict[str, int]:
    return {
        "ready": 0,
        "active": 0,
        "attention": 0,
        "completed": 0,
        "terminating": 0,
        "restarts": 0,
    }


def _empty_workload_counts() -> dict[str, int]:
    return {"ready": 0, "total": 0, "scaled_down": 0, "attention": 0}


def aggregate(collection: dict[str, Any]) -> dict[str, Any]:
    resources = collection.get("resources") or {}
    errors = list(collection.get("errors") or [])
    context = collection.get("context") or ""

    pods = [classify_pod(item) for item in resources.get("pods") or []]
    workloads = []
    for key, kind in (
        ("deployments", "Deployment"),
        ("statefulsets", "StatefulSet"),
        ("daemonsets", "DaemonSet"),
    ):
        workloads.extend(classify_workload(item, kind) for item in resources.get(key) or [])

    by_namespace: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "pods": _empty_pod_counts(),
            "workloads": _empty_workload_counts(),
            "problems": [],
        }
    )

    totals_pods = _empty_pod_counts()
    totals_workloads = _empty_workload_counts()

    for pod in pods:
        namespace = pod["namespace"] or "_unknown"
        bucket = by_namespace[namespace]
        category = pod["category"]
        bucket["pods"][category] += 1
        totals_pods[category] += 1
        bucket["pods"]["restarts"] += pod["restarts"]
        totals_pods["restarts"] += pod["restarts"]
        if category in ("ready", "attention"):
            bucket["pods"]["active"] += 1
            totals_pods["active"] += 1
        if pod["problem"]:
            bucket["problems"].append(pod["problem"])

    for workload in workloads:
        namespace = workload["namespace"] or "_unknown"
        bucket = by_namespace[namespace]
        category = workload["category"]
        if category == "scaled_down":
            bucket["workloads"]["scaled_down"] += 1
            totals_workloads["scaled_down"] += 1
        else:
            bucket["workloads"]["total"] += 1
            totals_workloads["total"] += 1
            if category == "ready":
                bucket["workloads"]["ready"] += 1
                totals_workloads["ready"] += 1
            else:
                bucket["workloads"]["attention"] += 1
                totals_workloads["attention"] += 1
        if workload["problem"]:
            bucket["problems"].append(workload["problem"])

    namespaces = []
    for name in sorted(by_namespace):
        entry = by_namespace[name]
        entry["problems"].sort(key=lambda item: (item["kind"], item["name"]))
        namespaces.append(
            {
                "name": name,
                "pods": entry["pods"],
                "workloads": entry["workloads"],
                "problems": entry["problems"],
            }
        )

    # failed means every resource query failed; never treat that as healthy zeros.
    available = not bool(collection.get("failed"))
    warning = totals_pods["attention"] > 0 or totals_workloads["attention"] > 0
    return {
        "context": context,
        "namespace_filter": collection.get("namespace"),
        "available": available,
        "partial": bool(collection.get("partial")),
        "errors": errors,
        "pods": totals_pods,
        "workloads": totals_workloads,
        "warning": warning,
        "namespaces": namespaces,
    }
