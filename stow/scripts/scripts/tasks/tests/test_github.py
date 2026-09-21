import unittest
from unittest.mock import call, patch

from tasks.filters import AssigneeFilter
from tasks.github import GithubBackend, GithubError, install_command
from tasks.models import BackendIdentity, RelationshipKind
from tasks.process import ProcessError, ProcessErrorKind


class GithubValidationTests(unittest.TestCase):
    @patch("tasks.github.run_json", return_value={"nameWithOwner": "Acme/App"})
    @patch("tasks.github.run_text")
    def test_validate_checks_version_auth_and_repository(self, run_text, run_json):
        backend = GithubBackend()

        self.assertEqual(backend.validate(), "Acme/App")

        self.assertEqual(
            run_text.call_args_list,
            [
                call(["gh", "--version"], timeout=30),
                call(
                    [
                        "gh",
                        "auth",
                        "status",
                        "--active",
                        "--hostname",
                        "github.com",
                    ],
                    timeout=30,
                ),
            ],
        )
        run_json.assert_called_once_with(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            timeout=30,
        )

    @patch("tasks.github.sys.platform", "darwin")
    @patch("tasks.github.run_text")
    def test_missing_gh_has_macos_install_command(self, run_text):
        run_text.side_effect = ProcessError(
            ProcessErrorKind.NOT_FOUND, "gh", "Required command not found: gh"
        )

        with self.assertRaisesRegex(GithubError, "brew install gh"):
            GithubBackend().check_available()

    def test_arch_install_command(self):
        self.assertEqual(install_command("linux"), "sudo pacman -S github-cli")

    @patch("tasks.github.run_text")
    def test_auth_ignores_stale_unrelated_accounts(self, run_text):
        def auth_status(command, **_kwargs):
            if command == ["gh", "auth", "status"]:
                raise ProcessError(
                    ProcessErrorKind.FAILED,
                    "gh",
                    "stale account on unrelated host",
                    1,
                )
            return ""

        run_text.side_effect = auth_status

        GithubBackend().check_auth()

        run_text.assert_called_once_with(
            [
                "gh",
                "auth",
                "status",
                "--active",
                "--hostname",
                "github.com",
            ],
            timeout=30,
        )

    @patch("tasks.github.run_text")
    def test_auth_failure_has_login_guidance(self, run_text):
        run_text.side_effect = ProcessError(ProcessErrorKind.FAILED, "gh", "not logged in", 1)

        with self.assertRaisesRegex(GithubError, "gh auth login"):
            GithubBackend().check_auth()


class GithubListTests(unittest.TestCase):
    @staticmethod
    def issue(number, title=None):
        return {
            "number": number,
            "title": title or f"Issue {number}",
            "state": "OPEN",
            "assignees": [],
            "labels": [],
            "url": f"https://github.com/acme/app/issues/{number}",
        }

    @patch("tasks.github.run_json")
    def test_lists_open_issues_with_bounded_limit(self, run_json):
        run_json.return_value = [
            {
                "number": 7,
                "title": "Ship it",
                "state": "OPEN",
                "stateReason": None,
                "assignees": [{"login": "octocat"}],
                "labels": [{"name": "ready"}],
                "url": "https://github.com/acme/app/issues/7",
                "issueType": {"name": "Bug"},
            }
        ]

        issues = GithubBackend("acme/app", limit=25).list_issues()

        self.assertEqual(issues[0].identity.stable_id, "github:acme/app:7")
        self.assertEqual(issues[0].task_type, "Bug")
        self.assertEqual(issues[0].assignees, ("octocat",))
        self.assertEqual(issues[0].labels, ("ready",))
        command = run_json.call_args.args[0]
        self.assertEqual(command[:6], ["gh", "issue", "list", "--repo", "acme/app", "--state"])
        self.assertIn("open", command)
        self.assertEqual(command[command.index("--limit") + 1], "25")
        self.assertIn("issueType", command[command.index("--json") + 1].split(","))
        self.assertNotIn("--search", command)

    @patch("tasks.github.run_json")
    def test_missing_issue_type_falls_back_to_issue(self, run_json):
        run_json.return_value = [
            {
                "number": 8,
                "title": "Untyped",
                "state": "OPEN",
                "assignees": [],
                "labels": [],
                "url": "https://github.com/acme/app/issues/8",
            }
        ]

        issues = GithubBackend("acme/app").list_issues()

        self.assertEqual(issues[0].task_type, "Issue")

    @patch("tasks.github.run_json", return_value=[])
    def test_search_is_repository_scoped_and_combines_configured_filter(self, run_json):
        GithubBackend("acme/app", search="label:ready").search_issues("parser bug")

        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--repo") + 1], "acme/app")
        self.assertEqual(command[command.index("--search") + 1], "label:ready parser bug")

    @patch("tasks.github.run_json", return_value=[])
    def test_assigned_to_me_uses_gh_assignee_flag(self, run_json):
        GithubBackend("acme/app", search="label:ready").list_issues(
            "is:issue", AssigneeFilter.ME
        )

        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--assignee") + 1], "@me")
        self.assertEqual(command[command.index("--search") + 1], "label:ready is:issue")

    @patch("tasks.github.run_json", return_value=[])
    def test_unassigned_adds_search_qualifier(self, run_json):
        GithubBackend("acme/app", search="label:ready").list_issues(
            "milestone:v1", AssigneeFilter.UNASSIGNED
        )

        command = run_json.call_args.args[0]
        self.assertNotIn("--assignee", command)
        self.assertEqual(
            command[command.index("--search") + 1],
            "label:ready milestone:v1 no:assignee",
        )

    @patch("tasks.github.run_json", return_value=[])
    def test_assigned_to_anyone_adds_search_qualifier(self, run_json):
        GithubBackend("acme/app").search_issues("parser bug", AssigneeFilter.ASSIGNED_ANYONE)

        command = run_json.call_args.args[0]
        self.assertNotIn("--assignee", command)
        self.assertEqual(command[command.index("--search") + 1], "parser bug has:assignee")

    @patch("tasks.github.run_json")
    def test_me_or_unassigned_merges_deduplicates_and_caps_results(self, run_json):
        run_json.side_effect = [
            [self.issue(3), self.issue(1), self.issue(2)],
            [self.issue(2, "Duplicate"), self.issue(4), self.issue(5)],
        ]

        issues = GithubBackend("acme/app", limit=4, search="label:ready").list_issues(
            "sort:updated", AssigneeFilter.ME_OR_UNASSIGNED
        )

        self.assertEqual([issue.identity.key for issue in issues], ["3", "1", "2", "4"])
        self.assertEqual(len(run_json.call_args_list), 2)
        me_command = run_json.call_args_list[0].args[0]
        unassigned_command = run_json.call_args_list[1].args[0]
        self.assertEqual(me_command[me_command.index("--limit") + 1], "4")
        self.assertEqual(me_command[me_command.index("--assignee") + 1], "@me")
        self.assertEqual(
            me_command[me_command.index("--search") + 1],
            "label:ready sort:updated",
        )
        self.assertEqual(unassigned_command[unassigned_command.index("--limit") + 1], "4")
        self.assertNotIn("--assignee", unassigned_command)
        self.assertEqual(
            unassigned_command[unassigned_command.index("--search") + 1],
            "label:ready sort:updated no:assignee",
        )

    def test_rejects_unbounded_limit(self):
        for value in (0, 1001, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GithubBackend(limit=value)


class GithubDetailTests(unittest.TestCase):
    @patch("tasks.github.run_json")
    def test_direct_cross_repo_lookup_and_full_normalization(self, run_json):
        run_json.return_value = {
            "number": 12,
            "title": "Main issue",
            "state": "OPEN",
            "stateReason": "REOPENED",
            "assignees": [{"login": "alice"}],
            "labels": [{"name": "bug"}],
            "url": "https://github.com/acme/app/issues/12",
            "body": "Depends on #4 and other/tools#9.",
            "comments": [
                {
                    "author": {"login": "bob"},
                    "body": "Duplicate mention #4; see #8.",
                    "createdAt": "2026-01-02T03:04:05Z",
                    "url": "https://github.com/acme/app/issues/12#issuecomment-1",
                }
            ],
            "parent": {
                "number": 2,
                "title": "Parent",
                "url": "https://github.com/acme/app/issues/2",
            },
            "subIssues": [
                {
                    "number": 4,
                    "title": "Child",
                    "url": "https://github.com/acme/app/issues/4",
                }
            ],
            "blockedBy": {
                "nodes": [
                    {
                        "number": 5,
                        "title": "Blocker",
                        "repository": {"nameWithOwner": "Acme/Infra"},
                    }
                ]
            },
            "blocking": [
                {
                    "number": 6,
                    "title": "Blocked",
                    "url": "https://github.com/acme/app/issues/6",
                }
            ],
        }

        detail = GithubBackend("default/repo").get_issue("Acme/App#12")

        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--repo") + 1], "acme/app")
        self.assertIn("issueType", command[command.index("--json") + 1].split(","))
        self.assertEqual(detail.summary.status, "Reopened")
        self.assertEqual(detail.summary.task_type, "Issue")
        self.assertEqual(detail.comments[0].author, "bob")
        self.assertEqual(
            [
                (relation.kind, relation.target.stable_id, relation.summary)
                for relation in detail.relationships
            ],
            [
                (RelationshipKind.PARENT, "github:acme/app:2", "Parent"),
                (RelationshipKind.CHILD, "github:acme/app:4", "Child"),
                (RelationshipKind.BLOCKED_BY, "github:acme/infra:5", "Blocker"),
                (RelationshipKind.BLOCKS, "github:acme/app:6", "Blocked"),
                (RelationshipKind.MENTIONED, "github:other/tools:9", None),
                (RelationshipKind.MENTIONED, "github:acme/app:8", None),
            ],
        )

    @patch("tasks.github.run_json")
    def test_preserves_distinct_first_class_relationships_to_same_issue(self, run_json):
        related = {
            "number": 4,
            "title": "Related issue",
            "url": "https://github.com/acme/app/issues/4",
        }
        run_json.return_value = {
            "number": 3,
            "title": "Issue",
            "state": "OPEN",
            "assignees": [],
            "labels": [],
            "url": "https://github.com/acme/app/issues/3",
            "body": "Also mentions #4.",
            "comments": [],
            "parent": None,
            "subIssues": [related],
            "blockedBy": [related],
            "blocking": [],
        }

        detail = GithubBackend("acme/app").get_issue(3)

        self.assertEqual(
            [(relation.kind, relation.target.stable_id) for relation in detail.relationships],
            [
                (RelationshipKind.CHILD, "github:acme/app:4"),
                (RelationshipKind.BLOCKED_BY, "github:acme/app:4"),
            ],
        )

    @patch("tasks.github.run_json")
    def test_accepts_issue_url_and_skips_self_mentions(self, run_json):
        run_json.return_value = {
            "number": 3,
            "title": "Issue",
            "state": "OPEN",
            "assignees": [],
            "labels": [],
            "url": "https://github.com/acme/tools/issues/3",
            "body": "Self: #3",
            "comments": [],
            "parent": None,
            "subIssues": [],
            "blockedBy": [],
            "blocking": [],
        }

        detail = GithubBackend().get_issue("https://github.com/acme/tools/issues/3")

        self.assertEqual(detail.identity.repository, "acme/tools")
        self.assertEqual(detail.relationships, ())

    @patch("tasks.github.run_json", return_value={})
    def test_plain_number_uses_resolved_repository(self, run_json):
        backend = GithubBackend("acme/app")
        with self.assertRaises(GithubError):
            backend.get_issue(4)
        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--repo") + 1], "acme/app")

    def test_backend_identity_preserves_cross_repo_target(self):
        backend = GithubBackend("acme/app")
        identity = BackendIdentity.github(9, "other/tools")
        with patch("tasks.github.run_json", return_value=[]) as run_json:
            with self.assertRaises(GithubError):
                backend.get_issue(identity)
        command = run_json.call_args.args[0]
        self.assertEqual(command[command.index("--repo") + 1], "other/tools")


if __name__ == "__main__":
    unittest.main()
