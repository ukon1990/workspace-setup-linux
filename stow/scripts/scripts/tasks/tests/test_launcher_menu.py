"""Recent backend persistence, startup routing, and keyboard menu regressions."""

import asyncio
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tasks.cli import _project, main
from tasks.config import JiraConfig, TasksConfig
from tasks.github import GithubError
from tasks.launcher import load_recent_backend, save_recent_backend
from tasks.models import Backend
from tasks.tui.launcher import LauncherApp, LauncherSelection, ProjectPrompt
from textual.widgets import Input, OptionList, Static


class LauncherStateTests(unittest.TestCase):
    def test_default_invalid_state_and_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "launcher.yaml"
            self.assertIs(load_recent_backend(path), Backend.GITHUB)
            for backend in (Backend.JIRA, Backend.GITHUB):
                save_recent_backend(backend, path)
                self.assertIs(load_recent_backend(path), backend)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(), f"backend: {backend.value}\n")
            for raw in (
                "",
                "[",
                "backend: invalid",
                "[]",
                "backend: jira\nproject: PROJ",
                "backend: []",
            ):
                path.write_text(raw)
                self.assertIs(load_recent_backend(path), Backend.GITHUB)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_atomic_save_keeps_existing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.yaml"
            save_recent_backend(Backend.JIRA, path)
            with patch("tasks.launcher.os.replace", side_effect=OSError("read only")):
                with self.assertRaises(OSError):
                    save_recent_backend(Backend.GITHUB, path)
            self.assertIs(load_recent_backend(path), Backend.JIRA)
            self.assertEqual(list(path.parent.iterdir()), [path])


class LauncherRoutingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("tasks.cli.load_config", return_value=TasksConfig()))
        self.pick = self.stack.enter_context(patch("tasks.tui.launcher.pick_backend"))
        self.save = self.stack.enter_context(patch("tasks.cli.save_recent_backend"))
        self.stack.enter_context(patch("tasks.cli.load_recent_backend", return_value=Backend.JIRA))
        self.stack.enter_context(patch("tasks.cli.sys.stdin.isatty", return_value=True))
        self.stack.enter_context(patch("tasks.cli.sys.stdout.isatty", return_value=True))

    def test_bare_command_picker_runs_before_backend_and_forwards_arguments(self):
        self.pick.return_value = LauncherSelection(Backend.GITHUB)
        with patch("tasks.cli._run_github") as run:
            self.assertEqual(
                main(
                    [
                        "--repo",
                        "owner/repo",
                        "--query",
                        "bug",
                        "--limit",
                        "25",
                        "--search",
                        "label:bug",
                    ]
                ),
                0,
            )
            args = run.call_args.args[1]
            self.assertTrue(args.gh)
            self.assertFalse(args.jira)
            self.assertEqual(
                (args.repo, args.query, args.limit, args.search),
                ("owner/repo", "bug", 25, "label:bug"),
            )
            self.pick.assert_called_once_with(
                Backend.JIRA, needs_project=True, validate_project=_project
            )
            self.save.assert_not_called()

    def test_prompted_project_is_forwarded(self):
        self.pick.return_value = LauncherSelection(Backend.JIRA, "PROJ")
        with patch("tasks.cli._run_jira") as run:
            self.assertEqual(main([]), 0)
            self.assertEqual(run.call_args.args[1].project, "PROJ")
            self.assertTrue(run.call_args.args[1].jira)

    def test_existing_project_config_or_direct_target_skip_project_prompt(self):
        self.pick.return_value = LauncherSelection(Backend.JIRA)
        for arguments in (
            ["--project", "PROJ"],
            ["PROJ-12"],
            ["https://example.atlassian.net/browse/PROJ-12"],
        ):
            with patch("tasks.cli._run_jira"):
                self.assertEqual(main(arguments), 0)
                self.assertFalse(self.pick.call_args.kwargs["needs_project"])
        with (
            patch(
                "tasks.cli.load_config",
                return_value=TasksConfig(jira=JiraConfig(default_project="PROJ")),
            ),
            patch("tasks.cli._run_jira"),
        ):
            self.assertEqual(main([]), 0)
            self.assertFalse(self.pick.call_args.kwargs["needs_project"])

    def test_cancel_does_not_validate_or_persist(self):
        self.pick.return_value = None
        with patch("tasks.cli.GithubBackend") as github, patch("tasks.cli.JiraBackend") as jira:
            self.assertEqual(main([]), 0)
            github.assert_not_called()
            jira.assert_not_called()
            self.save.assert_not_called()

    def test_non_interactive_requires_flag(self):
        for surface in ("stdin", "stdout"):
            with (
                patch(f"tasks.cli.sys.{surface}.isatty", return_value=False),
                redirect_stderr(StringIO()) as stderr,
            ):
                with self.assertRaises(SystemExit) as error:
                    main([])
                self.assertEqual(error.exception.code, 2)
                self.assertIn("interactive terminal", stderr.getvalue())
        self.pick.assert_not_called()

    def test_explicit_flags_skip_picker_and_noninteractive_check(self):
        with patch("tasks.cli.sys.stdin.isatty", return_value=False):
            for arguments, target in (
                (["--gh"], "_run_github"),
                (["--jira", "--project", "PROJ"], "_run_jira"),
            ):
                with patch(f"tasks.cli.{target}") as run:
                    self.assertEqual(main(arguments), 0)
                    run.assert_called_once()
        self.pick.assert_not_called()

    def test_selected_backend_checks_incompatible_arguments(self):
        for selected, arguments in (
            (Backend.GITHUB, ["--project", "PROJ"]),
            (Backend.JIRA, ["--search", "label:bug"]),
        ):
            self.pick.return_value = LauncherSelection(
                selected, "PROJ" if selected is Backend.JIRA else None
            )
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main(arguments)
        self.save.assert_not_called()

    def test_successful_open_records_explicit_or_picked_backend_before_browser(self):
        self.pick.return_value = LauncherSelection(Backend.GITHUB)
        for arguments in (["--gh"], []):
            with (
                patch("tasks.cli.GithubBackend") as backend,
                patch("tasks.tui.run") as run,
                patch("tasks.cli.resolve_github_repository", return_value=None),
            ):
                backend.return_value.validate.return_value = "owner/repo"
                run.side_effect = lambda *args, **kwargs: self.save.assert_called_with(
                    Backend.GITHUB
                )
                self.assertEqual(main(arguments), 0)
                run.assert_called_once()
        with (
            patch("tasks.cli.JiraBackend") as backend,
            patch("tasks.tui.run") as run,
            patch("tasks.cli.resolve_github_repository", return_value=None),
        ):
            run.side_effect = lambda *args, **kwargs: self.save.assert_called_with(Backend.JIRA)
            self.assertEqual(main(["--jira", "--project", "PROJ"]), 0)
            backend.return_value.validate.assert_called_once()
            run.assert_called_once()

    def test_failed_validation_does_not_record_and_write_failure_warns(self):
        with patch("tasks.cli.GithubBackend") as backend, redirect_stderr(StringIO()):
            backend.return_value.validate.side_effect = GithubError("not authenticated")
            self.assertEqual(main(["--gh"]), 2)
        self.save.assert_not_called()
        self.save.side_effect = OSError("read only")
        with (
            patch("tasks.cli.GithubBackend") as backend,
            patch("tasks.tui.run") as run,
            patch("tasks.cli.resolve_github_repository", return_value=None),
            redirect_stderr(StringIO()) as stderr,
        ):
            backend.return_value.validate.return_value = "owner/repo"
            self.assertEqual(main(["--gh"]), 0)
            self.assertIn("could not remember backend", stderr.getvalue())
            run.assert_called_once()


class LauncherViewTests(unittest.TestCase):
    def test_order_initial_highlight_keyboard_enter_and_cancel(self):
        for recent, keys, expected in (
            (Backend.GITHUB, ["enter"], Backend.GITHUB),
            (Backend.JIRA, ["enter"], Backend.JIRA),
            (Backend.GITHUB, ["j", "k", "down", "enter"], Backend.JIRA),
            (Backend.JIRA, ["escape"], None),
            (Backend.GITHUB, ["q"], None),
        ):
            app = LauncherApp(recent, needs_project=False, validate_project=_project)

            async def run(app=app, recent=recent, keys=keys):
                async with app.run_test() as pilot:
                    options = app.query_one(OptionList)
                    self.assertEqual(options.highlighted, 0)
                    self.assertEqual(options.get_option_at_index(0).id, recent.value)
                    await pilot.press(*keys)

            asyncio.run(run())
            self.assertEqual(app.return_value, LauncherSelection(expected) if expected else None)

    def test_project_retry_escape_and_normalization(self):
        app = LauncherApp(Backend.JIRA, needs_project=True, validate_project=_project)

        async def run():
            async with app.run_test() as pilot:
                await pilot.press("enter")
                self.assertIsInstance(app.screen, ProjectPrompt)
                app.screen.query_one(Input).value = "invalid key"
                await pilot.press("enter")
                self.assertIsInstance(app.screen, ProjectPrompt)
                self.assertIn("valid Jira project key", str(app.screen.query_one("#project-error", Static).content))
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, ProjectPrompt)
                await pilot.press("enter")
                app.screen.query_one(Input).value = " proj "
                await pilot.press("enter")

        asyncio.run(run())
        self.assertEqual(app.return_value, LauncherSelection(Backend.JIRA, "PROJ"))
