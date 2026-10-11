"""Loading progress remains informative while a backend request is pending."""

import unittest
from unittest.mock import patch

from textual.app import App

from tasks.tui.loading import LoadingPanel
from tasks.tui.logic import PhaseRunner, SyncProgress


class LoadingProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_timer_wrapping_and_cleanup(self):
        class TestApp(App):
            def compose(self):
                yield LoadingPanel()

        app = TestApp()
        async with app.run_test(size=(40, 24)) as pilot:
            panel = app.query_one(LoadingPanel)
            with patch("tasks.tui.loading.time.monotonic", return_value=100):
                panel.start("owner/a-long-repository-name", "GitHub")
                panel.advance(SyncProgress(0, 0, "Fetch", stage="Fetch issues", completed=True, issue_count=42))
                panel.advance(SyncProgress(0, 0, "Check", stage="Check relationships", operation="Fetching owner/repo#214", completed_checks=6))
            with patch("tasks.tui.loading.time.monotonic", return_value=112):
                panel.refresh_progress()
            await pilot.pause()
            text = str(panel.content)
            self.assertIn("12s elapsed", text)
            self.assertIn("✓ Fetch issues · 42 loaded", text)
            self.assertIn("6 checks completed", text)
            self.assertIn("Fetching owner/repo#214", text)
            self.assertIn("Still waiting for GitHub", text)
            panel.stop()
            self.assertIsNone(panel.timer)
            self.assertEqual(str(panel.content), "")
            panel.start("another/repo", "Jira")
            self.assertEqual(panel.stages, {})
            panel.remove()
            await pilot.pause()
            self.assertIsNone(panel.timer)

    async def test_phase_completion_follows_result(self):
        events = []
        runner = PhaseRunner(["Fetching issues"], events.append)
        def fetch():
            self.assertFalse(events[-1].completed)
            return [1, 2]
        self.assertEqual(runner.run("Fetching issues", fetch), [1, 2])
        self.assertTrue(events[-1].completed)
        self.assertEqual(events[-1].issue_count, 2)

    async def test_failed_lookup_counts_only_after_returning(self):
        from tasks.models import BackendIdentity, TaskSummary
        from tasks.tui.logic import TasksController

        events = []
        class Backend:
            backend_label = "GitHub"
            scope_label = "owner/repo"
            def list_tasks(self, **kwargs):
                return [TaskSummary(BackendIdentity.github(1, "owner/repo"), "Seed", "OPEN", dependencies_complete=False)]
            def get_task(self, identity, **kwargs):
                self_test.assertEqual(events[-1].completed_checks, 0)
                self_test.assertEqual(events[-1].operation, "Fetching owner/repo#1")
                raise RuntimeError("Unavailable")
        self_test = self
        controller = TasksController(Backend())
        state = controller.make_list_state()
        controller.load_list(state, on_progress=events.append)
        checks = [event for event in events if event.completed_checks is not None]
        self.assertEqual(checks[-1].completed_checks, 1)
        self.assertTrue(checks[-1].completed)
        self.assertEqual(events[-1].stage, "Prepare view")
        self.assertTrue(events[-1].completed)

    async def test_panel_updates_while_backend_is_blocked(self):
        import threading
        from textual import work

        release = threading.Event()
        pending = threading.Event()

        class TestApp(App):
            def compose(self):
                yield LoadingPanel()

            def on_mount(self):
                self.query_one(LoadingPanel).start("owner/repo", "GitHub")
                self.fetch()

            @work(thread=True)
            def fetch(self):
                panel = self.query_one(LoadingPanel)
                runner = PhaseRunner(["Fetching issues"], lambda p: self.call_from_thread(panel.advance, p))
                def delayed_backend():
                    pending.set()
                    release.wait(5)
                    return [1]
                runner.run("Fetching issues", delayed_backend)

        app = TestApp()
        try:
            async with app.run_test(size=(40, 24)) as pilot:
                await pilot.pause()
                self.assertTrue(pending.is_set())
                panel = app.query_one(LoadingPanel)
                with patch("tasks.tui.loading.time.monotonic", return_value=panel.started + 12):
                    panel.refresh_progress()
                self.assertIn("Still waiting for GitHub", str(panel.content))
                release.set()
                await pilot.pause()
                self.assertIn("✓ Fetch issues · 1 loaded", str(panel.content))
        finally:
            release.set()
