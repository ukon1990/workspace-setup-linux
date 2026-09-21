"""Unit tests for GitHub pull-request adapter and TUI helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tasks.models import CiState, Comment, PullDetail, PullSummary, ReviewComment
from tasks.pulls import (
    GithubPullsBackend,
    _normalize_summary,
    _rollup_ci,
    comments_for_path,
    format_review_comments,
    format_unified_diff,
    group_review_threads,
    resolve_github_repository,
    review_comment_markers,
    review_comments_by_anchor,
    split_diff_by_file,
)
from tasks.review_views import (
    file_view_status,
    hunk_fingerprint,
    load_viewed_files,
    mark_file_viewed,
)
from tasks.tui.pulls import (
    PullListState,
    PullsController,
    filter_pulls,
    set_pull_filter,
    sort_pulls,
    visible_pulls,
)


def _pr(
    number: int,
    *,
    title: str = "Title",
    ci: CiState = CiState.UNKNOWN,
    author: str = "alice",
    status: str = "Open",
) -> PullSummary:
    return PullSummary(
        repository="acme/app",
        number=number,
        title=title,
        status=status,
        author=author,
        ci_state=ci,
        url=f"https://github.com/acme/app/pull/{number}",
    )


class ResolveRepositoryTests(unittest.TestCase):
    def test_prefers_explicit_then_config_then_gh(self):
        from tasks.process import ProcessError, ProcessErrorKind

        self.assertEqual(
            resolve_github_repository(explicit="Owner/Repo", config_default="cfg/repo"),
            "owner/repo",
        )
        self.assertEqual(
            resolve_github_repository(explicit=None, config_default="Cfg/Repo"),
            "cfg/repo",
        )
        with patch("tasks.pulls.run_json", return_value={"nameWithOwner": "From/Cwd"}):
            self.assertEqual(
                resolve_github_repository(explicit=None, config_default=None),
                "from/cwd",
            )
        with patch(
            "tasks.pulls.run_json",
            side_effect=ProcessError(ProcessErrorKind.FAILED, "gh", "nope"),
        ):
            self.assertIsNone(
                resolve_github_repository(explicit=None, config_default=None)
            )


class NormalizePullTests(unittest.TestCase):
    def test_normalize_summary_maps_ci_rollup(self):
        payload = {
            "number": 12,
            "title": "Fix parser",
            "state": "OPEN",
            "isDraft": False,
            "author": {"login": "bob"},
            "assignees": [{"login": "carol"}],
            "labels": [{"name": "bug"}],
            "url": "https://github.com/acme/app/pull/12",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS"},
                {"conclusion": "FAILURE"},
            ],
        }
        summary = _normalize_summary(payload, "acme/app")
        self.assertEqual(summary.display_key, "acme/app#12")
        self.assertEqual(summary.author, "bob")
        self.assertEqual(summary.assignees, ("carol",))
        self.assertEqual(summary.ci_state, CiState.FAIL)

    def test_rollup_prefers_fail_over_pending_and_pass(self):
        self.assertEqual(
            _rollup_ci(
                [
                    {"bucket": "pass"},
                    {"bucket": "pending"},
                    {"bucket": "fail"},
                ]
            ),
            CiState.FAIL,
        )
        self.assertEqual(_rollup_ci([{"bucket": "pass"}]), CiState.PASS)
        self.assertEqual(_rollup_ci([]), CiState.UNKNOWN)

    def test_list_and_diff_commands(self):
        backend = GithubPullsBackend("Acme/App", limit=50)
        with patch("tasks.pulls.run_json", return_value=[]) as run_json:
            backend.list_pulls()
            command = run_json.call_args.args[0]
            self.assertEqual(command[:5], ["gh", "pr", "list", "--repo", "acme/app"])
            self.assertIn("--json", command)
            self.assertIn("statusCheckRollup", command[command.index("--json") + 1])

        with patch("tasks.pulls.run_text", return_value="diff --git a/x") as run_text:
            text = backend.get_diff(7)
            self.assertEqual(text, "diff --git a/x")
            command = run_text.call_args.args[0]
            self.assertEqual(
                command,
                ["gh", "pr", "diff", "7", "--repo", "acme/app", "--color", "never"],
            )

        with patch("tasks.pulls.run_json", return_value=[]) as run_json:
            backend.list_checks(7)
            command = run_json.call_args.args[0]
            self.assertEqual(
                command[:6],
                ["gh", "pr", "checks", "7", "--repo", "acme/app"],
            )


class SplitDiffTests(unittest.TestCase):
    def test_split_diff_by_file_handles_add_modify_rename(self):
        patch = """\
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+hello
+world
diff --git a/old.txt b/old.txt
--- a/old.txt
+++ b/old.txt
@@ -1 +1 @@
-a
+b
diff --git a/before.md b/after.md
similarity index 90%
rename from before.md
rename to after.md
--- a/before.md
+++ b/after.md
@@ -1 +1 @@
-old
+new
"""
        files = split_diff_by_file(patch)
        self.assertEqual([item.label for item in files], [
            "new.py",
            "old.txt",
            "before.md → after.md",
        ])
        self.assertEqual((files[0].added, files[0].deleted), (2, 0))
        self.assertEqual((files[1].added, files[1].deleted), (1, 1))
        self.assertTrue(files[2].hunk.startswith("diff --git a/before.md b/after.md"))

    def test_empty_diff_returns_no_files(self):
        self.assertEqual(split_diff_by_file(""), [])
        self.assertEqual(split_diff_by_file("   \n"), [])

    def test_exclude_patterns_and_summarize(self):
        from tasks.pulls import path_is_excluded, summarize_diff_files

        patch = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-a
+b
diff --git a/src/app/generated/api/x.ts b/src/app/generated/api/x.ts
--- a/src/app/generated/api/x.ts
+++ b/src/app/generated/api/x.ts
@@ -0,0 +1,3 @@
+one
+two
+three
diff --git a/Form.Designer.cs b/Form.Designer.cs
--- a/Form.Designer.cs
+++ b/Form.Designer.cs
@@ -1 +1 @@
-x
+y
"""
        patterns = ("src/app/generated/api", "**/*.Designer.cs")
        self.assertTrue(path_is_excluded("src/app/generated/api/x.ts", patterns))
        self.assertTrue(path_is_excluded("Form.Designer.cs", patterns))
        self.assertFalse(path_is_excluded("src/app.py", patterns))
        files = split_diff_by_file(patch, exclude_patterns=patterns)
        self.assertEqual([item.excluded for item in files], [False, True, True])
        added, deleted, added_excl, deleted_excl = summarize_diff_files(files)
        self.assertEqual((added, deleted), (5, 2))
        self.assertEqual((added_excl, deleted_excl), (1, 1))


class UnifiedDiffFormatTests(unittest.TestCase):
    def test_format_unified_diff_gutters_and_strips_headers(self):
        patch = """\
diff --git a/demo.py b/demo.py
index 111..222 100644
--- a/demo.py
+++ b/demo.py
@@ -10,4 +10,5 @@ def demo():
 context
-removed
+added
+also
 keep
"""
        rendered = format_unified_diff(patch)
        plain = rendered.plain
        self.assertNotIn("diff --git", plain)
        self.assertNotIn("--- a/demo.py", plain)
        self.assertIn("@@ -10,4 +10,5 @@ def demo():", plain)
        lines = plain.splitlines()
        # hunk header, then context/old/new lines with gutters
        self.assertTrue(lines[0].rstrip().endswith("@@ -10,4 +10,5 @@ def demo():"))
        self.assertRegex(lines[1], r"^\s*10\s+10\s+│  context$")
        self.assertRegex(lines[2], r"^\s*11\s+│ -removed$")
        self.assertRegex(lines[3], r"^\s*11\s+│ \+added$")
        self.assertRegex(lines[4], r"^\s*12\s+│ \+also$")
        self.assertRegex(lines[5], r"^\s*12\s+13\s+│  keep$")

    def test_format_unified_diff_empty(self):
        self.assertEqual(format_unified_diff("").plain, "(empty diff)")
        headers_only = "diff --git a/x b/x\n--- a/x\n+++ b/x\n"
        self.assertEqual(format_unified_diff(headers_only).plain, "(no hunks)")

    def test_format_unified_diff_marks_comment_lines(self):
        patch = """\
@@ -1,2 +1,2 @@
 context
-old
+new
"""
        comments = (
            ReviewComment(
                id=1,
                path="demo.py",
                body="Please rename",
                author="alice",
                side="RIGHT",
                line=2,
                start_line=1,
            ),
            ReviewComment(
                id=2,
                path="demo.py",
                body="Agreed",
                author="bob",
                side="RIGHT",
                line=2,
                start_line=1,
                in_reply_to_id=1,
            ),
        )
        anchored = review_comments_by_anchor(comments, "demo.py")
        rendered = format_unified_diff(
            patch,
            line_markers=review_comment_markers(comments, "demo.py"),
            comments_by_anchor=anchored,
        )
        plain = rendered.plain
        self.assertIn("●2", plain)
        self.assertIn("┃", plain)  # multi-line range mark on start line
        self.assertIn("RIGHT:1–2", plain)
        self.assertIn("alice", plain)
        self.assertIn("Please rename", plain)
        self.assertIn("bob", plain)
        self.assertIn("(reply)", plain)
        self.assertIn("Agreed", plain)


class ReviewCommentTests(unittest.TestCase):
    def test_list_review_comments_command_and_normalize(self):
        backend = GithubPullsBackend("acme/app")
        payload = [
            {
                "id": 9,
                "path": "src/a.py",
                "body": "nit",
                "user": {"login": "bob"},
                "side": "RIGHT",
                "line": 12,
                "start_line": 10,
                "created_at": "2026-01-02T03:04:05Z",
                "html_url": "https://example.test/c/9",
            }
        ]
        with patch("tasks.pulls.run_json", return_value=payload) as run_json:
            comments = backend.list_review_comments(3)
            command = run_json.call_args.args[0]
            self.assertEqual(command[:3], ["gh", "api", "repos/acme/app/pulls/3/comments"])
            self.assertIn("--paginate", command)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].path, "src/a.py")
        self.assertEqual(comments[0].anchor_line, 12)
        self.assertEqual(comments_for_path(comments, "src/a.py")[0].author, "bob")
        self.assertEqual(review_comment_markers(comments, "src/a.py"), {("RIGHT", 12): 1})
        self.assertIn("nit", format_review_comments(comments))

    def test_group_review_threads(self):
        comments = (
            ReviewComment(id=1, path="a.py", body="root", author="a", line=3),
            ReviewComment(
                id=2, path="a.py", body="reply", author="b", line=3, in_reply_to_id=1
            ),
            ReviewComment(id=3, path="a.py", body="other", author="c", line=9),
        )
        threads = group_review_threads(comments)
        self.assertEqual(len(threads), 2)
        self.assertEqual([c.id for c in threads[0]], [1, 2])
        text = format_review_comments(comments)
        self.assertIn("(reply)", text)
        self.assertIn("other", text)


class ReviewViewsTests(unittest.TestCase):
    def test_mark_viewed_and_stale(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "views.yaml"
            pull_id = "github-pr:acme/app:7"
            fingerprint = hunk_fingerprint("diff body")
            self.assertEqual(
                file_view_status(pull_id, "a.py", fingerprint, path=path), "new"
            )
            mark_file_viewed(pull_id, "a.py", fingerprint, path=path)
            self.assertEqual(
                file_view_status(pull_id, "a.py", fingerprint, path=path), "viewed"
            )
            self.assertEqual(
                file_view_status(pull_id, "a.py", "other", path=path), "stale"
            )
            self.assertEqual(load_viewed_files(pull_id, path=path)["a.py"], fingerprint)


class PullListHelperTests(unittest.TestCase):
    def test_filter_and_sort_keep_independent_state(self):
        pulls = [
            _pr(1, title="Alpha", ci=CiState.PASS, author="zoe"),
            _pr(2, title="Beta fail", ci=CiState.FAIL, author="alice"),
            _pr(3, title="Gamma", ci=CiState.PENDING, author="bob"),
        ]
        filtered = filter_pulls(pulls, "fail")
        self.assertEqual([p.number for p in filtered], [2])

        by_ci = sort_pulls(pulls, "ci", reverse=False)
        self.assertEqual([p.ci_state for p in by_ci], [
            CiState.FAIL,
            CiState.PENDING,
            CiState.PASS,
        ])

        state_a = PullListState(pulls=list(pulls), filter_text="", index=0)
        state_b = PullListState(pulls=list(pulls), filter_text="beta", index=0)
        set_pull_filter(state_b, "beta")
        self.assertEqual(len(visible_pulls(state_a)), 3)
        self.assertEqual([p.number for p in visible_pulls(state_b)], [2])
        self.assertEqual(state_a.index, 0)


class PullsControllerTests(unittest.TestCase):
    def test_load_list_and_detail_cache(self):
        backend = GithubPullsBackend("acme/app")
        summary = _pr(9, ci=CiState.PASS)
        detail = PullDetail(
            summary=summary,
            description="body",
            comments=(Comment(author="a", body="hi"),),
            checks=(),
        )
        controller = PullsController(backend)
        state = controller.make_list_state()
        with patch.object(backend, "list_pulls", return_value=(summary,)) as list_pulls:
            controller.load_list(state, refresh=True)
            list_pulls.assert_called_once()
            self.assertEqual(state.pulls, [summary])

        with patch.object(backend, "get_pull", return_value=detail) as get_pull:
            loaded, error = controller.load_detail(summary)
            self.assertIsNone(error)
            self.assertIs(loaded, detail)
            get_pull.assert_called_once_with(9)
            again, _ = controller.load_detail(summary)
            self.assertIs(again, detail)
            get_pull.assert_called_once()

        with patch.object(backend, "get_diff", return_value="+line") as get_diff:
            text, error = controller.load_diff(summary)
            self.assertEqual(text, "+line")
            self.assertIsNone(error)
            get_diff.assert_called_once_with(9)

    def test_repo_error_short_circuits(self):
        controller = PullsController(None)
        state = controller.make_list_state(repo_error="missing repo")
        controller.load_list(state)
        self.assertEqual(state.error, "missing repo")
        self.assertEqual(state.pulls, [])


class CliPullsWiringTests(unittest.TestCase):
    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.JiraBackend")
    @patch("tasks.cli.load_config")
    @patch("tasks.cli.resolve_github_repository", return_value="owner/repo")
    def test_jira_passes_pulls_backend_when_repo_resolves(
        self, resolve_repo, load_config, backend_type, run, load_filter
    ):
        from tasks.cli import main
        from tasks.filters import FilterLoadResult
        from tasks.pulls import GithubPullsBackend

        load_config.return_value.jira.default_project = "PROJ"
        load_config.return_value.github.default_repo = None
        load_config.return_value.github.limit = 100
        load_filter.return_value = FilterLoadResult()

        self.assertEqual(main(["--jira", "--repo", "owner/repo"]), 0)
        resolve_repo.assert_called_once()
        kwargs = run.call_args.kwargs
        self.assertIsInstance(kwargs["pulls_backend"], GithubPullsBackend)
        self.assertEqual(kwargs["pulls_backend"].repository, "owner/repo")
        self.assertIsNone(kwargs["pulls_error"])

    @patch("tasks.cli.load_assignee_filter")
    @patch("tasks.tui.run")
    @patch("tasks.cli.JiraBackend")
    @patch("tasks.cli.load_config")
    @patch("tasks.cli.resolve_github_repository", return_value=None)
    def test_jira_sets_pulls_error_when_unresolved(
        self, resolve_repo, load_config, backend_type, run, load_filter
    ):
        from tasks.cli import main
        from tasks.filters import FilterLoadResult

        load_config.return_value.jira.default_project = "PROJ"
        load_config.return_value.github.default_repo = None
        load_config.return_value.github.limit = 100
        load_filter.return_value = FilterLoadResult()

        self.assertEqual(main(["--jira"]), 0)
        self.assertIsNone(run.call_args.kwargs["pulls_backend"])
        self.assertIn("No GitHub repository", run.call_args.kwargs["pulls_error"])


class SelectionAndSuggestionTests(unittest.TestCase):
    def test_selection_github_anchor_prefers_right_side(self):
        from tasks.pulls import parse_diff_rows, selection_github_anchor, suggestion_fence

        patch = """\
@@ -1,3 +1,3 @@
 context
-old
+new
"""
        rows = parse_diff_rows(patch)
        # select deletion + addition
        del_idx = next(i for i, row in enumerate(rows) if row.kind == "del")
        add_idx = next(i for i, row in enumerate(rows) if row.kind == "add")
        side, start, end, texts = selection_github_anchor(rows, del_idx, add_idx)
        self.assertEqual(side, "RIGHT")
        self.assertEqual((start, end), (2, 2))
        self.assertEqual(texts, ("new",))
        self.assertEqual(suggestion_fence(texts), "```suggestion\nnew\n```")

    def test_selection_left_side_for_deletions_only(self):
        from tasks.pulls import parse_diff_rows, selection_github_anchor

        patch = """\
@@ -1,2 +1,1 @@
-gone
 keep
"""
        rows = parse_diff_rows(patch)
        del_idx = next(i for i, row in enumerate(rows) if row.kind == "del")
        side, start, end, texts = selection_github_anchor(rows, del_idx, del_idx)
        self.assertEqual(side, "LEFT")
        self.assertEqual((start, end), (1, 1))
        self.assertEqual(texts, ("gone",))

    def test_multi_line_right_selection(self):
        from tasks.pulls import parse_diff_rows, selection_github_anchor

        patch = """\
@@ -1,1 +1,3 @@
+one
+two
 keep
"""
        rows = parse_diff_rows(patch)
        first = next(i for i, row in enumerate(rows) if row.kind == "add")
        second = first + 1
        side, start, end, texts = selection_github_anchor(rows, first, second)
        self.assertEqual(side, "RIGHT")
        self.assertEqual((start, end), (1, 2))
        self.assertEqual(texts, ("one", "two"))


class SubmitReviewTests(unittest.TestCase):
    @patch("tasks.pulls.run_json")
    @patch("tasks.pulls.run_text", return_value="abc123\n")
    def test_submit_review_posts_payload(self, run_text, run_json):
        run_json.return_value = {"id": 1}
        backend = GithubPullsBackend("owner/repo")
        backend.submit_review(
            7,
            "COMMENT",
            body="LGTM-ish",
            comments=[
                {
                    "path": "a.py",
                    "side": "RIGHT",
                    "line": 12,
                    "start_line": 10,
                    "body": "nit",
                }
            ],
        )
        run_text.assert_called_once()
        self.assertIn("pulls/7", run_text.call_args.args[0][2])
        command = run_json.call_args.args[0]
        self.assertEqual(command[:4], ["gh", "api", "--method", "POST"])
        self.assertIn("pulls/7/reviews", command[4])
        import json

        payload = json.loads(run_json.call_args.kwargs["input_text"])
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual(payload["commit_id"], "abc123")
        self.assertEqual(payload["body"], "LGTM-ish")
        self.assertEqual(payload["comments"][0]["start_line"], 10)
        self.assertEqual(payload["comments"][0]["start_side"], "RIGHT")


if __name__ == "__main__":
    unittest.main()
