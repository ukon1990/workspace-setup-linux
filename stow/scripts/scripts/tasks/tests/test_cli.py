import os
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from tasks.cli import GithubTuiBackend, JiraTuiBackend, build_parser, main
from tasks.filters import AssigneeFilter, FilterLoadResult
from tasks.github import GithubError
from tasks.models import BackendIdentity, TaskDetail, TaskSummary

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
LAUNCHER = SCRIPTS_DIR / "tasks.sh"
SETUP = SCRIPTS_DIR / "tasks-setup.sh"
TEST_ROOT = Path(__file__).resolve().parent / ".tasks-integration-test"


def summary(identity):
    return TaskSummary(identity, "Title", "OPEN")


class ParserTests(unittest.TestCase):
    def test_requires_exactly_one_backend(self):
        parser = build_parser()
        for arguments in ([], ["--jira", "--gh"]):
            with (
                self.subTest(arguments=arguments),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args(arguments)

    def test_rejects_cross_backend_options(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                main(["--gh", "--project", "PROJ"])
            with self.assertRaises(SystemExit):
                main(["--jira", "--repo", "owner/repo"])


class AdapterTests(unittest.TestCase):
    def test_jira_adapter_retains_scope_and_routes_calls(self):
        backend = Mock()
        identity = BackendIdentity.jira("PROJ-7")
        detail = TaskDetail(summary(identity))
        backend.list_tasks.return_value = (summary(identity),)
        backend.search_tasks.return_value = (summary(identity),)
        backend.get_task.return_value = detail
        adapter = JiraTuiBackend(backend, "PROJ", limit=25, jql_extra="priority = High")

        self.assertEqual(adapter.scope_label, "PROJ")
        adapter.list_tasks(assignee_filter=AssigneeFilter.ME)
        adapter.list_tasks(
            "parser",
            refresh=True,
            assignee_filter=AssigneeFilter.UNASSIGNED,
        )
        self.assertIs(adapter.get_task(identity, refresh=True), detail)

        backend.list_tasks.assert_called_once_with(
            "PROJ",
            limit=25,
            jql_extra="priority = High",
            assignee_filter=AssigneeFilter.ME,
        )
        backend.search_tasks.assert_called_once_with(
            "PROJ",
            "parser",
            limit=25,
            jql_extra="priority = High",
            assignee_filter=AssigneeFilter.UNASSIGNED,
        )
        backend.get_task.assert_called_once_with("PROJ-7")

    def test_github_adapter_retains_scope_and_routes_calls(self):
        backend = Mock()
        identity = BackendIdentity.github(7, "owner/repo")
        detail = TaskDetail(summary(identity))
        backend.list_issues.return_value = (summary(identity),)
        backend.search_issues.return_value = (summary(identity),)
        backend.get_issue.return_value = detail
        adapter = GithubTuiBackend(backend, "owner/repo")

        self.assertEqual(adapter.scope_label, "owner/repo")
        adapter.list_tasks(assignee_filter=AssigneeFilter.ME_OR_UNASSIGNED)
        adapter.list_tasks(
            "parser",
            refresh=True,
            assignee_filter=AssigneeFilter.ASSIGNED_ANYONE,
        )
        self.assertIs(adapter.get_task(identity, refresh=True), detail)

        backend.list_issues.assert_called_once_with(assignee_filter=AssigneeFilter.ME_OR_UNASSIGNED)
        backend.search_issues.assert_called_once_with(
            "parser", assignee_filter=AssigneeFilter.ASSIGNED_ANYONE
        )
        backend.get_issue.assert_called_once_with(identity)


class MainTests(unittest.TestCase):
    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.JiraBackend")
    @patch("tasks.cli.load_config")
    def test_resolves_direct_jira_identity_before_tui(
        self, load_config, backend_type, run, load_filter
    ):
        load_config.return_value.jira.default_project = "OTHER"
        load_filter.return_value = FilterLoadResult(AssigneeFilter.ME)
        backend = backend_type.return_value

        self.assertEqual(main(["--jira", "proj-42"]), 0)

        backend.validate.assert_called_once_with()
        load_filter.assert_called_once_with("jira:PROJ")
        identity = run.call_args.kwargs["initial_identity"]
        self.assertEqual(identity.stable_id, "jira:PROJ-42")
        self.assertEqual(run.call_args.args[0].scope_label, "PROJ")
        self.assertIs(run.call_args.kwargs["initial_assignee_filter"], AssigneeFilter.ME)

    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.GithubBackend")
    @patch("tasks.cli.load_config")
    def test_resolves_direct_github_number_after_repository_validation(
        self, load_config, backend_type, run, load_filter
    ):
        load_config.return_value.github.default_repo = None
        load_config.return_value.github.limit = 100
        load_config.return_value.github.search = None
        backend_type.return_value.validate.return_value = "owner/repo"
        load_filter.return_value = FilterLoadResult(AssigneeFilter.UNASSIGNED)

        self.assertEqual(main(["--gh", "42"]), 0)

        load_filter.assert_called_once_with("github:owner/repo")
        identity = run.call_args.kwargs["initial_identity"]
        self.assertEqual(identity.stable_id, "github:owner/repo:42")
        self.assertEqual(run.call_args.args[0].scope_label, "owner/repo")
        self.assertIs(
            run.call_args.kwargs["initial_assignee_filter"],
            AssigneeFilter.UNASSIGNED,
        )

    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.GithubBackend")
    @patch("tasks.cli.load_config")
    def test_qualified_github_target_overrides_config_default(
        self, load_config, backend_type, run, load_filter
    ):
        load_config.return_value.github.default_repo = "other/repo"
        load_config.return_value.github.limit = 100
        load_config.return_value.github.search = None
        backend_type.return_value.validate.return_value = "owner/repo"
        load_filter.return_value = FilterLoadResult()

        self.assertEqual(main(["--gh", "owner/repo#42"]), 0)

        backend_type.assert_called_once_with("owner/repo", limit=100, search=None)
        self.assertEqual(
            run.call_args.kwargs["initial_identity"].stable_id,
            "github:owner/repo:42",
        )

    @patch("tasks.cli.clear_assignee_filter")
    @patch("tasks.cli.save_assignee_filter")
    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.GithubBackend")
    @patch("tasks.cli.load_config")
    def test_filter_callback_saves_and_clears_resolved_repository_scope(
        self,
        load_config,
        backend_type,
        run,
        load_filter,
        save_filter,
        clear_filter,
    ):
        load_config.return_value.github.default_repo = "Other/Repo"
        load_config.return_value.github.limit = 100
        load_config.return_value.github.search = None
        backend_type.return_value.validate.return_value = "Owner/Repo"
        load_filter.return_value = FilterLoadResult()

        self.assertEqual(main(["--gh"]), 0)

        load_filter.assert_called_once_with("github:owner/repo")
        callback = run.call_args.kwargs["on_assignee_filter_change"]
        callback(AssigneeFilter.ME_OR_UNASSIGNED)
        callback(AssigneeFilter.ALL)
        save_filter.assert_called_once_with("github:owner/repo", AssigneeFilter.ME_OR_UNASSIGNED)
        clear_filter.assert_called_once_with("github:owner/repo")

    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.JiraBackend")
    @patch("tasks.cli.load_config")
    def test_filter_load_warning_falls_back_to_all(
        self, load_config, backend_type, run, load_filter
    ):
        load_config.return_value.jira.default_project = "PROJ"
        load_filter.return_value = FilterLoadResult(
            warning="Could not read filter state filters.yaml: invalid YAML"
        )

        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["--jira"]), 0)

        self.assertIn("tasks: warning: Could not read filter state", stderr.getvalue())
        self.assertIs(
            run.call_args.kwargs["initial_assignee_filter"],
            AssigneeFilter.ALL,
        )

    @patch("tasks.cli.GithubBackend")
    def test_maps_backend_error_to_nonzero_exit(self, backend_type):
        backend_type.return_value.validate.side_effect = GithubError(
            "GitHub CLI is not authenticated. Run: gh auth login"
        )

        with patch("sys.stderr") as stderr:
            self.assertEqual(main(["--gh", "--repo", "owner/repo"]), 2)

        self.assertIn(
            "gh auth login", "".join(call.args[0] for call in stderr.write.call_args_list)
        )


class LauncherTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        TEST_ROOT.mkdir()
        self.addCleanup(shutil.rmtree, TEST_ROOT, True)

    def test_setup_dry_run_is_symlink_safe(self):
        linked = TEST_ROOT / "tasks-setup"
        linked.symlink_to(SETUP)

        result = subprocess.run(
            [str(linked)],
            env=dict(
                os.environ,
                DRY_RUN="1",
                PYTHON_BIN="missing-python",
                TASKS_VENV=str(TEST_ROOT / "venv"),
            ),
            cwd=TEST_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(TEST_ROOT / "venv"), result.stdout)
        self.assertIn("tasks/requirements.txt", result.stdout)

    def test_setup_rejects_unsafe_runtime_paths(self):
        for venv in ("", "venv", "/", str(Path.home()), str(TEST_ROOT / "runtime")):
            with self.subTest(venv=venv):
                result = subprocess.run(
                    [str(SETUP)],
                    env=dict(os.environ, DRY_RUN="1", TASKS_VENV=venv),
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ending in /venv", result.stderr)

    def test_setup_refuses_broken_runtime_without_deleting_it(self):
        venv = TEST_ROOT / "venv"
        venv.mkdir()
        sentinel = venv / "keep-me"
        sentinel.write_text("safe")

        result = subprocess.run(
            [str(SETUP)],
            env=dict(os.environ, TASKS_VENV=str(venv)),
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "safe")
        self.assertIn("Tasks runtime is broken", result.stderr)
        self.assertIn("Move or remove it, then run:", result.stderr)

    def test_launcher_resolves_symlink_and_preserves_cwd(self):
        linked = TEST_ROOT / "tasks"
        linked.symlink_to(LAUNCHER)
        venv = TEST_ROOT / "venv"
        python = venv / "bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "-c" && "$2" == *"import yaml, tasks"* ]]; then exit 0; fi\n'
            'printf "%s\\n" "$PWD" "$PYTHONPATH" "$*"\n'
        )
        python.chmod(0o755)

        result = subprocess.run(
            [str(linked), "--gh", "7"],
            env=dict(os.environ, TASKS_VENV=str(venv)),
            cwd=TEST_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], str(TEST_ROOT))
        self.assertEqual(lines[1], str(SCRIPTS_DIR))
        self.assertIn("runpy.run_module", lines[2])
        self.assertTrue(lines[2].endswith(f" {TEST_ROOT} {SCRIPTS_DIR} --gh 7"))

    def test_launcher_reports_missing_imports_without_traceback(self):
        venv = TEST_ROOT / "venv"
        python = venv / "bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "-c" && "$2" == *"import yaml, tasks"* ]]; then\n'
            '  echo "Traceback" >&2\n'
            "  exit 1\n"
            "fi\n"
            "exit 1\n"
        )
        python.chmod(0o755)

        result = subprocess.run(
            [str(LAUNCHER), "--gh"],
            env=dict(os.environ, TASKS_VENV=str(venv)),
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(
            f"Run: TASKS_VENV={venv} {SETUP}",
            result.stderr,
        )

    def test_launcher_probes_and_runs_on_python_without_safe_path_flag(self):
        venv = TEST_ROOT / "venv"
        python = venv / "bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/usr/bin/env bash\n"
            '[[ "$1" == "-P" ]] && exit 2\n'
            'if [[ "$1" == "-c" && "$2" == *"import yaml, tasks"* ]]; then exit 0; fi\n'
            'printf "%s\\n" "$*"\n'
        )
        python.chmod(0o755)

        result = subprocess.run(
            [str(LAUNCHER), "--jira"],
            env=dict(os.environ, TASKS_VENV=str(venv)),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-P", result.stdout)
        self.assertIn("runpy.run_module", result.stdout)
        self.assertTrue(result.stdout.strip().endswith(f" {Path.cwd()} {SCRIPTS_DIR} --jira"))

    def test_launcher_works_when_caller_is_trusted_scripts_directory(self):
        result = subprocess.run(
            [str(LAUNCHER), "--help"],
            env=dict(
                os.environ,
                TASKS_VENV=str(Path.home() / ".local/share/tasks/venv"),
            ),
            cwd=SCRIPTS_DIR,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--jira", result.stdout)
        self.assertIn("--gh", result.stdout)

    def test_launcher_ignores_malicious_modules_in_caller_cwd(self):
        venv = TEST_ROOT / "venv"
        create = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(create.returncode, 0, create.stderr)
        install = subprocess.run(
            [
                str(venv / "bin/python"),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-q",
                "-r",
                str(SCRIPTS_DIR / "tasks/requirements.txt"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(install.returncode, 0, install.stderr)

        tasks_marker = TEST_ROOT / "tasks-imported"
        yaml_marker = TEST_ROOT / "yaml-imported"
        (TEST_ROOT / "tasks.py").write_text(
            f"from pathlib import Path\nPath({str(tasks_marker)!r}).touch()\n"
        )
        (TEST_ROOT / "yaml.py").write_text(
            f"from pathlib import Path\nPath({str(yaml_marker)!r}).touch()\n"
        )

        result = subprocess.run(
            [str(LAUNCHER), "--help"],
            env=dict(os.environ, TASKS_VENV=str(venv)),
            cwd=TEST_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(tasks_marker.exists())
        self.assertFalse(yaml_marker.exists())


if __name__ == "__main__":
    unittest.main()
