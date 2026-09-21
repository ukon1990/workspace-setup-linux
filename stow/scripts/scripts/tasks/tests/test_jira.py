import unittest
from unittest.mock import patch

from tasks.config import JiraConfig
from tasks.filters import AssigneeFilter
from tasks.jira import JiraBackend, JiraError
from tasks.models import RelationshipKind
from tasks.process import ProcessError, ProcessErrorKind


class JiraValidationTests(unittest.TestCase):
    @patch("tasks.jira.run_text")
    def test_validate_checks_version_then_auth(self, run):
        run.side_effect = ["acli version 1.2.3\n", "Authenticated\n"]

        self.assertEqual(JiraBackend().validate(), "1.2.3")
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [["acli", "--version"], ["acli", "jira", "auth", "status"]],
        )

    @patch("tasks.jira.sys.platform", "darwin")
    @patch("tasks.jira.run_text")
    def test_missing_acli_has_official_macos_install_guidance(self, run):
        process_error = ProcessError(
            ProcessErrorKind.NOT_FOUND, "acli", "Required command not found: acli"
        )
        run.side_effect = process_error

        with self.assertRaises(JiraError) as raised:
            JiraBackend().check_available()

        self.assertIs(raised.exception.process_error, process_error)
        self.assertIs(raised.exception.__cause__, process_error)
        self.assertIn("brew tap atlassian/homebrew-acli", str(raised.exception))
        self.assertIn("brew install acli", str(raised.exception))

    @patch("tasks.jira.sys.platform", "linux")
    @patch("tasks.jira.run_text")
    def test_missing_acli_has_official_linux_guidance(self, run):
        run.side_effect = ProcessError(
            ProcessErrorKind.NOT_FOUND, "acli", "Required command not found: acli"
        )

        with self.assertRaisesRegex(JiraError, "install-linux"):
            JiraBackend().check_available()

    @patch("tasks.jira.run_text", return_value="development build")
    def test_rejects_unrecognized_version(self, _run):
        with self.assertRaisesRegex(JiraError, "unrecognized version"):
            JiraBackend().check_available()

    @patch("tasks.jira.run_text")
    def test_auth_error_wraps_process_error_without_detail(self, run):
        process_error = ProcessError(
            ProcessErrorKind.FAILED,
            "acli",
            "acli exited: Authorization: Bearer secret-token",
        )
        run.side_effect = process_error

        with self.assertRaises(JiraError) as raised:
            JiraBackend().check_auth()

        self.assertIs(raised.exception.process_error, process_error)
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertIn("acli jira auth login", str(raised.exception))

    @patch("tasks.jira.run_text", return_value="Authenticated: No\n")
    def test_auth_status_rejects_logged_out_account(self, _run):
        with self.assertRaises(JiraError) as raised:
            JiraBackend().check_auth()

        self.assertIsInstance(raised.exception.process_error, ProcessError)
        self.assertIn("acli jira auth login", str(raised.exception))


class JiraQueryTests(unittest.TestCase):
    @staticmethod
    def _jql(run):
        argv = run.call_args.args[0]
        return argv[argv.index("--jql") + 1]

    @patch("tasks.jira.run_json", return_value=[])
    def test_lists_bounded_non_done_project_items(self, run):
        backend = JiraBackend(JiraConfig(default_project="PROJ", limit=25))

        self.assertEqual(backend.list_tasks(), ())

        argv = run.call_args.args[0]
        jql = argv[argv.index("--jql") + 1]
        self.assertEqual(
            jql,
            'project = "PROJ" AND statusCategory != Done ORDER BY updated DESC',
        )
        self.assertEqual(argv[argv.index("--limit") + 1], "25")
        self.assertEqual(
            argv[argv.index("--fields") + 1],
            "key,issuetype,summary,status,assignee,priority,parent,issuelinks",
        )

    @patch("tasks.jira.run_json", return_value=[])
    def test_list_applies_each_assignee_filter(self, run):
        expected = {
            AssigneeFilter.ALL: None,
            AssigneeFilter.ME: "assignee = currentUser()",
            AssigneeFilter.UNASSIGNED: "assignee is EMPTY",
            AssigneeFilter.ME_OR_UNASSIGNED: (
                "(assignee = currentUser() OR assignee is EMPTY)"
            ),
            AssigneeFilter.ASSIGNED_ANYONE: "assignee is not EMPTY",
        }

        for assignee_filter, clause in expected.items():
            with self.subTest(assignee_filter=assignee_filter):
                JiraBackend().list_tasks("PROJ", assignee_filter=assignee_filter)

                clauses = ['project = "PROJ"', "statusCategory != Done"]
                if clause:
                    clauses.append(clause)
                self.assertEqual(
                    self._jql(run),
                    " AND ".join(clauses) + " ORDER BY updated DESC",
                )

    @patch("tasks.jira.run_json", return_value={"issues": []})
    def test_search_escapes_text_and_combines_configured_and_cli_jql(self, run):
        backend = JiraBackend(JiraConfig(default_project="PROJ", jql_extra='labels = "ready"'))

        backend.search_tasks(
            None,
            'quote " and slash \\',
            jql_extra="assignee = currentUser()",
            limit=10,
            assignee_filter=AssigneeFilter.ME_OR_UNASSIGNED,
        )

        argv = run.call_args.args[0]
        jql = argv[argv.index("--jql") + 1]
        self.assertIn(
            '(summary ~ "quote \\\\\\" and slash \\\\\\\\" '
            'OR description ~ "quote \\\\\\" and slash \\\\\\\\")',
            jql,
        )
        self.assertIn('(labels = "ready")', jql)
        self.assertIn("(assignee = currentUser())", jql)
        self.assertTrue(jql.endswith("ORDER BY updated DESC"))
        self.assertLess(jql.index('project = "PROJ"'), jql.index("statusCategory != Done"))
        self.assertLess(
            jql.index("statusCategory != Done"),
            jql.index("(assignee = currentUser() OR assignee is EMPTY)"),
        )
        self.assertLess(
            jql.index("(assignee = currentUser() OR assignee is EMPTY)"),
            jql.index("(summary ~"),
        )
        self.assertLess(jql.index("(summary ~"), jql.index('(labels = "ready")'))
        self.assertLess(
            jql.index('(labels = "ready")'),
            jql.rindex("(assignee = currentUser())"),
        )

    @patch("tasks.jira.run_json", return_value={"issues": []})
    def test_search_escapes_lucene_reserved_characters(self, run):
        backend = JiraBackend(JiraConfig(default_project="PROJ"))

        backend.search_tasks(
            None,
            'brackets [x] wildcard *? path /\\ quote " punctuation +-!(){}^~:&|',
        )

        argv = run.call_args.args[0]
        jql = argv[argv.index("--jql") + 1]
        escaped = (
            "brackets \\\\[x\\\\] wildcard \\\\*\\\\? path \\\\/\\\\\\\\ "
            'quote \\\\\\" punctuation \\\\+\\\\-\\\\!\\\\(\\\\)\\\\{\\\\}'
            "\\\\^\\\\~\\\\:\\\\&\\\\|"
        )
        self.assertIn(f'summary ~ "{escaped}"', jql)
        self.assertIn(f'description ~ "{escaped}"', jql)

    @patch("tasks.jira.run_json", return_value={"issues": []})
    def test_search_leaves_extra_jql_untouched(self, run):
        raw_extra = 'summary ~ "[release]*?" AND labels = "ready\\now"'

        JiraBackend(JiraConfig(default_project="PROJ")).search_tasks(
            None,
            "safe",
            jql_extra=raw_extra,
        )

        argv = run.call_args.args[0]
        jql = argv[argv.index("--jql") + 1]
        self.assertIn(f"({raw_extra})", jql)

    def test_requires_valid_project_query_and_limit(self):
        backend = JiraBackend()
        with self.assertRaisesRegex(JiraError, "project is required"):
            backend.list_tasks()
        with self.assertRaisesRegex(JiraError, "valid project key"):
            backend.list_tasks('PROJ" OR project = SECRET')
        with self.assertRaisesRegex(JiraError, "non-empty"):
            backend.search_tasks("PROJ", " ")
        with self.assertRaisesRegex(JiraError, "1 to 1000"):
            backend.list_tasks("PROJ", limit=1001)

    @patch("tasks.jira.run_json")
    def test_search_error_wraps_process_error_without_command_details(self, run):
        process_error = ProcessError(
            ProcessErrorKind.FAILED, "acli", "acli failed with password=secret"
        )
        run.side_effect = process_error

        with self.assertRaises(JiraError) as raised:
            JiraBackend().list_tasks("PROJ")

        self.assertIs(raised.exception.process_error, process_error)
        self.assertEqual(str(raised.exception), "Could not search Jira work items.")


class JiraNormalizationTests(unittest.TestCase):
    @patch("tasks.jira.run_json")
    def test_normalizes_search_results(self, run):
        run.return_value = {
            "issues": [
                {
                    "key": "PROJ-2",
                    "self": "https://jira.example/rest/api/3/issue/10002",
                    "fields": {
                        "summary": "Ship task browser",
                        "status": {"name": "In Progress"},
                        "issuetype": {"name": "Story"},
                        "priority": {"name": "High"},
                        "assignee": {"displayName": "Ada"},
                        "labels": ["cli", "ready"],
                        "components": [{"name": "Platform"}],
                        "issuelinks": [
                            {
                                "type": {
                                    "outward": "blocks",
                                    "inward": "is blocked by",
                                },
                                "outwardIssue": {
                                    "key": "PROJ-4",
                                    "fields": {"summary": "Blocked task"},
                                },
                            },
                            {
                                "type": {
                                    "outward": "blocks",
                                    "inward": "is blocked by",
                                },
                                "inwardIssue": {
                                    "key": "PROJ-5",
                                    "fields": {"summary": "Blocker"},
                                },
                            },
                        ],
                    },
                }
            ]
        }

        tasks = JiraBackend().list_tasks("proj")

        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task.identity.stable_id, "jira:PROJ-2")
        self.assertEqual(task.title, "Ship task browser")
        self.assertEqual(task.status, "In Progress")
        self.assertEqual(task.task_type, "Story")
        self.assertEqual(task.priority, "High")
        self.assertEqual(task.assignees, ("Ada",))
        self.assertEqual(task.labels, ("cli", "ready"))
        self.assertEqual(task.components, ("Platform",))
        self.assertEqual(task.url, "https://jira.example/browse/PROJ-2")
        self.assertEqual([item.key for item in task.blocked_by], ["PROJ-5"])
        self.assertEqual([item.key for item in task.blocks], ["PROJ-4"])

    @patch("tasks.jira.run_json")
    def test_direct_url_lookup_normalizes_full_detail_and_relations(self, run):
        run.return_value = {
            "key": "PROJ-2",
            "self": "https://jira.example/rest/api/3/issue/10002",
            "fields": {
                "summary": "Implement backend",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "description": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "See PROJ-3 and PROJ-8."},
                                {
                                    "type": "text",
                                    "text": "Docs",
                                    "marks": [
                                        {
                                            "type": "link",
                                            "attrs": {"href": "https://example.test"},
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "bulletList",
                            "content": [
                                {
                                    "type": "listItem",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [{"type": "text", "text": "Read only"}],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                },
                "comment": {
                    "comments": [
                        {
                            "author": {"displayName": "Grace"},
                            "created": "2026-09-20T10:00:00Z",
                            "body": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "mention", "attrs": {"text": "@Linus"}},
                                            {"type": "text", "text": "check PROJ-9"},
                                        ],
                                    }
                                ],
                            },
                        }
                    ]
                },
                "parent": {
                    "key": "PROJ-1",
                    "fields": {"summary": "Parent"},
                },
                "subtasks": [
                    {"key": "PROJ-3", "fields": {"summary": "Child"}},
                ],
                "issuelinks": [
                    {
                        "type": {"outward": "blocks", "inward": "is blocked by"},
                        "outwardIssue": {
                            "key": "PROJ-4",
                            "fields": {"summary": "Blocked task"},
                        },
                    },
                    {
                        "type": {"outward": "blocks", "inward": "is blocked by"},
                        "inwardIssue": {
                            "key": "PROJ-5",
                            "fields": {"summary": "Blocker"},
                        },
                    },
                    {
                        "type": {"outward": "duplicates", "inward": "is duplicated by"},
                        "outwardIssue": {
                            "key": "PROJ-6",
                            "fields": {"summary": "Duplicate"},
                        },
                    },
                ],
            },
        }

        detail = JiraBackend().get_task("https://jira.example/browse/PROJ-2")

        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["acli", "jira", "workitem", "view", "PROJ-2"])
        self.assertIn("comment", argv[argv.index("--fields") + 1])
        self.assertEqual(detail.identity.stable_id, "jira:PROJ-2")
        self.assertIn("See PROJ-3 and PROJ-8.", detail.description)
        self.assertIn("Docs (https://example.test)", detail.description)
        self.assertIn("- Read only", detail.description)
        self.assertEqual(detail.comments[0].author, "Grace")
        self.assertIn("@Linus check PROJ-9", detail.comments[0].body)

        relations = {
            relation.target.key: (relation.kind, relation.label, relation.summary)
            for relation in detail.relationships
        }
        self.assertEqual(relations["PROJ-1"], (RelationshipKind.PARENT, "parent", "Parent"))
        self.assertEqual(relations["PROJ-3"], (RelationshipKind.CHILD, "subtask", "Child"))
        self.assertEqual(
            relations["PROJ-4"],
            (RelationshipKind.BLOCKS, "blocks", "Blocked task"),
        )
        self.assertEqual(
            relations["PROJ-5"],
            (RelationshipKind.BLOCKED_BY, "is blocked by", "Blocker"),
        )
        self.assertEqual(
            relations["PROJ-6"],
            (RelationshipKind.RELATED, "duplicates", "Duplicate"),
        )
        self.assertEqual(
            relations["PROJ-8"][:2],
            (RelationshipKind.MENTIONED, "mentioned"),
        )
        self.assertEqual(
            relations["PROJ-9"][:2],
            (RelationshipKind.MENTIONED, "mentioned"),
        )

    @patch("tasks.jira.run_json")
    def test_mentions_deduplicate_self_and_first_class_relations(self, run):
        run.return_value = {
            "key": "ABC-1",
            "summary": "Task",
            "status": "Open",
            "description": "ABC-1 ABC-2 ABC-3 ABC-3",
            "subtasks": [{"key": "ABC-2", "summary": "Child"}],
        }

        detail = JiraBackend().get_task("ABC-1")

        self.assertEqual(
            [relation.target.key for relation in detail.relationships],
            ["ABC-2", "ABC-3"],
        )

    @patch("tasks.jira.run_json", return_value={"unexpected": "shape"})
    def test_rejects_unexpected_json_shape(self, _run):
        with self.assertRaisesRegex(JiraError, "unexpected Jira search response"):
            JiraBackend().list_tasks("PROJ")

    def test_rejects_invalid_direct_identity_without_process_call(self):
        with self.assertRaisesRegex(JiraError, "Expected a Jira key"):
            JiraBackend().get_task("not-an-issue")


if __name__ == "__main__":
    unittest.main()
