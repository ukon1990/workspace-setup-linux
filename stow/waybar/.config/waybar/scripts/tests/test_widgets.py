import importlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import status_widgets as loader
from widgets import cpu, gpu, kubernetes, memory, network, processes, state
from widgets.common import run, use_compact_perf_text


def increment(cache, legacy):
    state.CACHE_DIR = Path(cache)
    state.LEGACY_PATH = Path(legacy)
    for _ in range(15):
        with state.transaction("cpu") as data:
            data["count"] = data.get("count", 0) + 1


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "widgets"
        self.legacy = Path(self.temp.name) / "legacy.json"
        for key, value in [("CACHE_DIR", self.cache), ("LEGACY_PATH", self.legacy)]:
            patcher = patch.object(state, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_migration_and_independent_state(self):
        original = {"hyprsunset": {"enabled": True, "temperature": 3500}, "cpu_history": [5]}
        self.legacy.write_text(json.dumps(original))
        with state.transaction("hyprsunset") as data:
            self.assertEqual(data, {"hyprsunset": original["hyprsunset"]})
        with state.transaction("cpu") as data:
            self.assertEqual(data, {"cpu_history": [5]})
        self.assertEqual(json.loads(self.legacy.read_text()), original)

    def test_concurrent_updates(self):
        context = multiprocessing.get_context("fork")
        workers = [
            context.Process(target=increment, args=(str(self.cache), str(self.legacy)))
            for _ in range(4)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(json.loads((self.cache / "cpu.json").read_text())["count"], 60)

    def test_failed_transaction_preserves_state(self):
        with state.transaction("cpu") as data:
            data["count"] = 3
        with self.assertRaises(RuntimeError):
            with state.transaction("cpu") as data:
                data["count"] = 4
                raise RuntimeError("failure")
        self.assertEqual(json.loads((self.cache / "cpu.json").read_text())["count"], 3)

    def test_registry_and_escape(self):
        for widget, handler in (loader.MODULES | loader.ACTIONS).values():
            self.assertTrue(
                callable(getattr(importlib.import_module(f"widgets.{widget}"), handler))
            )
        with patch.object(cpu, "cpu_module", return_value={"text": "CPU", "tooltip": "x < y & z"}):
            payload = loader.dispatch("cpu", [])
        self.assertEqual(payload["tooltip"], "x &lt; y &amp; z")
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_action_routing(self):
        from widgets import hyprsunset

        with patch.object(hyprsunset, "hyprsunset_adjust") as handler:
            self.assertIsNone(loader.dispatch("hyprsunset-adjust", ["-250"]))
            self.assertEqual(handler.call_args.args[1], ["-250"])

    def test_hyprsunset_menu_uses_shared_wofi_dropdown(self):
        from widgets import hyprsunset

        with (
            patch.object(hyprsunset.shutil, "which", return_value="/usr/bin/wofi"),
            patch.object(
                hyprsunset.wofi_anchor,
                "wofi_menu_args",
                return_value=["--insensitive", "--normal-window"],
            ) as menu_args,
            patch.object(
                hyprsunset.wofi_anchor,
                "run_wofi_menu",
                return_value="",
            ) as run_menu,
        ):
            hyprsunset.hyprsunset_menu({}, [])

        menu_args.assert_called_once_with(hyprsunset.MENU_WIDTH, hyprsunset.MENU_HEIGHT)
        self.assertEqual(run_menu.call_args.args[0][-2:], ["--insensitive", "--normal-window"])
        self.assertIn("Edit schedule…", run_menu.call_args.kwargs["input_text"])

    def test_process_ranking_and_pid_reuse(self):
        old = {"1": {"ticks": 100, "start": "5"}}
        current = {
            "1": {"ticks": 300, "start": "5", "rss": 1000, "name": "worker"},
            "2": {"ticks": 900, "start": "9", "rss": 2000, "name": "other"},
        }
        with patch.object(os, "sysconf", return_value=100):
            self.assertEqual(processes.top_cpu(current, old, 2), [(100.0, "1", "worker")])
            old["1"]["start"] = "4"
            self.assertEqual(processes.top_cpu(current, old, 2), [])
        self.assertEqual(processes.top_memory(current)[0], (2000, "2", "other"))

    def test_proc_parser_handles_parentheses_and_disappearing_processes(self):
        root = Path(self.temp.name)
        (root / "42").mkdir()
        fields = ["0"] * 22
        fields[11], fields[12], fields[19], fields[21] = "100", "50", "123", "2"
        (root / "42/stat").write_text("42 (a (worker)) " + " ".join(fields))
        (root / "43").mkdir()
        with patch.object(processes, "PROC", root):
            data = processes.snapshot()
        self.assertEqual(data["42"]["name"], "a (worker)")
        self.assertEqual(data["42"]["ticks"], 150)
        self.assertNotIn("43", data)

    def test_network_rates_and_reset(self):
        previous = {"iface": "eth0", "rx": 100, "tx": 200, "time": 10}
        self.assertEqual(network.rates(previous, "eth0", 300, 600, 12), (100, 200))
        self.assertEqual(network.rates(previous, "eth1", 300, 600, 12), (0, 0))
        self.assertEqual(network.rates(previous, "eth0", 0, 600, 12), (0, 0))
        with patch.object(network, "default_route", return_value={}):
            data = {"net_prev": previous}
            self.assertIn("No active", network.network_module(data)["tooltip"])
            self.assertNotIn("net_prev", data)

    def test_gpu_partial_and_missing_data(self):
        result = subprocess.CompletedProcess([], 0, "GPU, 20, 1024, 4096, 40, [N/A], 300\n")
        with (
            patch.object(gpu, "run", return_value=result),
            patch.object(gpu, "use_compact_perf_text", return_value=True),
        ):
            tooltip = gpu.gpu_module({})["tooltip"]
            self.assertIn("25.0%", tooltip)
            self.assertIn("Power draw: Unavailable", tooltip)
        with (
            patch.object(gpu, "run", return_value=subprocess.CompletedProcess([], 1, "")),
            patch.object(gpu, "use_compact_perf_text", return_value=True),
        ):
            self.assertIn("unavailable", gpu.gpu_module({})["tooltip"])

    def test_memory_swap_and_cache(self):
        fixture = "MemTotal: 8192 kB\nMemAvailable: 2048 kB\nCached: 1000 kB\nSReclaimable: 100 kB\nShmem: 50 kB\nSwapTotal: 2048 kB\nSwapFree: 1024 kB\n"
        with (
            patch.object(Path, "read_text", return_value=fixture),
            patch.object(memory, "snapshot", return_value={}),
            patch.object(memory, "use_compact_perf_text", return_value=True),
        ):
            tooltip = memory.memory_module({})["tooltip"]
        self.assertIn("75.0%", tooltip)
        self.assertIn("Swap: 1.0 MiB / 2.0 MiB", tooltip)
        self.assertIn("Cache: 1.0 MiB", tooltip)

    def test_cpu_delta_and_first_sample(self):
        def read(path, *args, **kwargs):
            if str(path) == "/proc/stat":
                return "cpu 100 0 0 100 0 0 0 0 100 0\n"
            return "model name : Test CPU\nphysical id : 0\ncore id : 0\n"

        with (
            patch.object(Path, "read_text", read),
            patch.object(cpu, "snapshot", return_value={}),
            patch.object(cpu, "temperature", return_value="Unavailable"),
            patch.object(cpu, "use_compact_perf_text", return_value=True),
        ):
            self.assertIn("Collecting", cpu.cpu_module({})["tooltip"])
            payload = cpu.cpu_module({"cpu_prev": {"total": 100, "idle": 50}})
            self.assertIn("CPU usage: 50.0%", payload["tooltip"])

    def test_metric_command_failures(self):
        for failure in [FileNotFoundError(), subprocess.TimeoutExpired("tool", 3)]:
            with patch("widgets.common.subprocess.run", side_effect=failure):
                self.assertEqual(run(["tool"]).returncode, 1)

    def test_monitor_compact_layout(self):
        result = subprocess.CompletedProcess([], 0, '[{"name": "DP-1", "width": 2560}]')
        with (
            patch("widgets.common.run", return_value=result),
            patch("widgets.common.PERF_PRIMARY_MONITOR", "DP-1"),
        ):
            self.assertTrue(use_compact_perf_text({}))

    def test_kubernetes_widget_formats_status(self):
        problems = [
            {"kind": "Pod", "name": f"p{i}", "reason": "Pending", "restarts": 0} for i in range(12)
        ]
        status = {
            "context": "demo",
            "available": True,
            "partial": False,
            "errors": [],
            "warning": True,
            "pods": {
                "ready": 1,
                "active": 2,
                "attention": 1,
                "completed": 0,
                "terminating": 0,
                "restarts": 0,
            },
            "workloads": {"ready": 1, "total": 1, "scaled_down": 0, "attention": 0},
            "namespaces": [
                {
                    "name": "alpha",
                    "pods": {
                        "ready": 1,
                        "active": 2,
                        "attention": 1,
                        "completed": 0,
                        "terminating": 0,
                        "restarts": 3,
                    },
                    "workloads": {"ready": 1, "total": 1, "scaled_down": 0, "attention": 0},
                    "problems": problems,
                }
            ],
        }
        with patch.object(kubernetes, "_load_status", return_value=status):
            payload = kubernetes.kubernetes_module({})
        self.assertEqual(payload["text"], "󰠳 P 1/2 W 1/1 !1")
        self.assertIn("warning", payload["class"])
        self.assertIn("Context: demo", payload["tooltip"])
        self.assertIn("…and 2 more", payload["tooltip"])
        with patch.object(
            kubernetes,
            "_load_status",
            return_value={
                "available": False,
                "errors": ["no context"],
                "context": "",
                "pods": {},
                "workloads": {},
                "namespaces": [],
            },
        ):
            muted = kubernetes.kubernetes_module({})
        self.assertEqual(muted["text"], "󰠳 n/a")
        self.assertIn("muted", muted["class"])


if __name__ == "__main__":
    unittest.main()
