import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "stow/scripts/scripts/kube-status.sh"
sys.path.insert(0, str(SCRIPT.parent))

from kube_status import aggregate, collect, render  # noqa: E402
from kube_status.cli import main, run  # noqa: E402


def pod(
    namespace,
    name,
    *,
    phase="Running",
    ready=True,
    restarts=0,
    deleting=False,
    waiting=None,
    containers=1,
):
    container_statuses = []
    for index in range(containers):
        status = {
            "name": f"c{index}",
            "ready": ready if index == 0 else True,
            "restartCount": restarts if index == 0 else 0,
            "state": {"running": {}},
        }
        if waiting and index == 0:
            status["ready"] = False
            status["state"] = {"waiting": {"reason": waiting}}
        container_statuses.append(status)
    metadata = {"namespace": namespace, "name": name}
    if deleting:
        metadata["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    return {
        "metadata": metadata,
        "spec": {"containers": [{"name": f"c{i}"} for i in range(containers)]},
        "status": {"phase": phase, "containerStatuses": container_statuses},
    }


def deployment(namespace, name, *, desired=1, ready=1, generation=1, observed=1):
    return {
        "metadata": {"namespace": namespace, "name": name, "generation": generation},
        "spec": {"replicas": desired},
        "status": {"readyReplicas": ready, "observedGeneration": observed},
    }


def statefulset(namespace, name, *, desired=1, ready=1, generation=1, observed=1):
    return deployment(namespace, name, desired=desired, ready=ready, generation=generation, observed=observed)


def daemonset(namespace, name, *, desired=1, ready=1, generation=1, observed=1):
    return {
        "metadata": {"namespace": namespace, "name": name, "generation": generation},
        "spec": {},
        "status": {
            "desiredNumberScheduled": desired,
            "numberReady": ready,
            "observedGeneration": observed,
        },
    }


class AggregateTests(unittest.TestCase):
    def test_mixed_namespaces_and_classifications(self):
        collection = {
            "context": "demo",
            "namespace": None,
            "errors": [],
            "partial": False,
            "failed": False,
            "resources": {
                "pods": [
                    pod("alpha", "ok"),
                    pod("alpha", "crash", waiting="CrashLoopBackOff", restarts=4),
                    pod("beta", "done", phase="Succeeded", ready=False),
                    pod("beta", "gone", deleting=True, ready=False),
                    pod("beta", "pending", phase="Pending", ready=False),
                ],
                "deployments": [
                    deployment("alpha", "api", desired=2, ready=2),
                    deployment("alpha", "worker", desired=2, ready=1),
                    deployment("beta", "idle", desired=0, ready=0),
                    deployment("beta", "stale", desired=1, ready=1, generation=3, observed=2),
                ],
                "statefulsets": [statefulset("alpha", "db")],
                "daemonsets": [daemonset("beta", "agent", desired=2, ready=2)],
            },
        }
        status = aggregate.aggregate(collection)
        self.assertTrue(status["available"])
        self.assertTrue(status["warning"])
        self.assertEqual(status["pods"]["ready"], 1)
        self.assertEqual(status["pods"]["active"], 3)
        self.assertEqual(status["pods"]["attention"], 2)
        self.assertEqual(status["pods"]["completed"], 1)
        self.assertEqual(status["pods"]["terminating"], 1)
        self.assertEqual(status["workloads"]["ready"], 3)
        self.assertEqual(status["workloads"]["total"], 5)
        self.assertEqual(status["workloads"]["scaled_down"], 1)
        self.assertEqual(status["workloads"]["attention"], 2)
        names = [entry["name"] for entry in status["namespaces"]]
        self.assertEqual(names, ["alpha", "beta"])
        alpha = status["namespaces"][0]
        reasons = [problem["reason"] for problem in alpha["problems"]]
        self.assertIn("CrashLoopBackOff", reasons)
        self.assertTrue(any("1/2 ready" in reason for reason in reasons))

    def test_empty_success_is_available(self):
        status = aggregate.aggregate(
            {
                "context": "empty",
                "errors": [],
                "partial": False,
                "failed": False,
                "resources": {
                    "pods": [],
                    "deployments": [],
                    "statefulsets": [],
                    "daemonsets": [],
                },
            }
        )
        self.assertTrue(status["available"])
        self.assertFalse(status["warning"])
        self.assertEqual(status["pods"]["active"], 0)
        self.assertEqual(status["workloads"]["total"], 0)

    def test_total_failure_is_unavailable(self):
        status = aggregate.aggregate(
            {
                "context": "down",
                "errors": ["pods: timed out"],
                "partial": False,
                "failed": True,
                "resources": {
                    "pods": [],
                    "deployments": [],
                    "statefulsets": [],
                    "daemonsets": [],
                },
            }
        )
        self.assertFalse(status["available"])
        text = render.render_terminal(status)
        self.assertIn("unavailable", text)
        self.assertIn("timed out", text)


class CollectTests(unittest.TestCase):
    def test_resolve_context_and_partial_results(self):
        with patch.object(collect, "run_kubectl") as runner:
            runner.return_value = collect._completed(["kubectl"], 0, "demo\n", "")
            self.assertEqual(collect.resolve_context(), "demo")

        responses = {
            "pods": collect._completed(
                ["kubectl"],
                0,
                json.dumps({"items": [pod("ns", "a")]}),
                "",
            ),
            "deployments": collect._completed(["kubectl"], 1, "", "deploy boom"),
            "statefulsets": collect._completed(["kubectl"], 0, '{"items":[]}', ""),
            "daemonsets": collect._completed(["kubectl"], 0, '{"items":[]}', ""),
        }

        def fake_run(args, kubectl="kubectl"):
            resource = args[1]
            return responses[resource]

        with (
            patch.object(collect.shutil, "which", return_value="/usr/bin/kubectl"),
            patch.object(collect, "run_kubectl", side_effect=fake_run),
        ):
            payload = collect.fetch_resources("demo")
        self.assertTrue(payload["partial"])
        self.assertFalse(payload["failed"])
        self.assertEqual(len(payload["resources"]["pods"]), 1)
        self.assertTrue(any("deployments:" in error for error in payload["errors"]))

    def test_missing_kubectl_and_malformed_json(self):
        with patch.object(collect.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "kubectl is not installed"):
                collect.fetch_resources("demo")

        with (
            patch.object(collect.shutil, "which", return_value="/usr/bin/kubectl"),
            patch.object(
                collect,
                "run_kubectl",
                return_value=collect._completed(["kubectl"], 0, "{bad", ""),
            ),
        ):
            payload = collect.fetch_resources("demo")
        self.assertTrue(payload["failed"])
        self.assertTrue(any("invalid JSON" in error for error in payload["errors"]))


class CliTests(unittest.TestCase):
    def test_json_and_argument_forwarding(self):
        fake_status = {
            "context": "demo",
            "namespace_filter": "alpha",
            "available": True,
            "partial": False,
            "errors": [],
            "pods": {
                "ready": 1,
                "active": 1,
                "attention": 0,
                "completed": 0,
                "terminating": 0,
                "restarts": 0,
            },
            "workloads": {"ready": 1, "total": 1, "scaled_down": 0, "attention": 0},
            "warning": False,
            "namespaces": [],
        }
        with (
            patch("kube_status.cli.resolve_context", return_value="demo") as resolve,
            patch("kube_status.cli.fetch_resources", return_value={"context": "demo"}) as fetch,
            patch("kube_status.cli.aggregate", return_value=fake_status),
        ):
            with patch("builtins.print") as printer:
                code = main(["--json", "--context", "demo", "--namespace", "alpha"])
        self.assertEqual(code, 0)
        resolve.assert_called_once_with("demo")
        fetch.assert_called_once_with("demo", namespace="alpha")
        printed = printer.call_args.args[0]
        self.assertEqual(json.loads(printed)["context"], "demo")

    def test_entry_points_help(self):
        import os

        linked = Path(tempfile.mkdtemp()) / "kube-status"
        linked.symlink_to(SCRIPT)
        for command in ([str(linked)], [sys.executable, "-P", "-m", "kube_status"]):
            result = subprocess.run(
                [*command, "--help"],
                cwd=linked.parent,
                env={**os.environ, "PYTHONPATH": str(SCRIPT.parent)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--json", result.stdout)
            self.assertIn("--context", result.stdout)

    def test_run_maps_value_errors(self):
        with patch("kube_status.cli.main", side_effect=ValueError("boom")):
            with patch("builtins.print") as printer:
                self.assertEqual(run([]), 1)
            self.assertIn("kube-status: boom", printer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
