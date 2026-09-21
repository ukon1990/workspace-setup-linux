import unittest

from tasks.models import BackendIdentity
from tasks.references import (
    github_identity,
    jira_identity,
    parse_github_references,
    parse_jira_references,
)


class JiraReferenceTests(unittest.TestCase):
    def test_extracts_urls_and_keys_once_and_skips_self(self):
        current = BackendIdentity.jira("PROJ-1")
        references = parse_jira_references(
            "PROJ-1 links PROJ-2 and https://jira.example.com/browse/PROJ-2",
            current=current,
        )
        self.assertEqual([item.target.display_key for item in references], ["PROJ-2"])

    def test_parses_direct_url(self):
        identity = jira_identity("https://jira.example.com/browse/ABC-42")
        self.assertEqual(identity.stable_id, "jira:ABC-42")


class GithubReferenceTests(unittest.TestCase):
    def test_extracts_contextual_cross_repo_and_urls(self):
        references = parse_github_references(
            "See #12, owner/other#8 and https://github.com/acme/tools/issues/3.",
            default_repo="acme/app",
        )
        self.assertEqual(
            [item.target.stable_id for item in references],
            [
                "github:acme/tools:3",
                "github:owner/other:8",
                "github:acme/app:12",
            ],
        )

    def test_deduplicates_and_skips_self(self):
        current = BackendIdentity.github(12, "acme/app")
        references = parse_github_references(
            "#12 and acme/app#13 and https://github.com/acme/app/issues/13",
            default_repo="acme/app",
            current=current,
        )
        self.assertEqual([item.target.display_key for item in references], ["acme/app#13"])

    def test_retains_pull_urls_as_cross_repo_mentions(self):
        references = parse_github_references(
            "See https://github.com/acme/tools/pull/8 and tools/app#8.",
            default_repo="acme/app",
        )
        self.assertEqual(
            [item.target.stable_id for item in references],
            ["github:acme/tools:8", "github:tools/app:8"],
        )
        self.assertEqual(
            references[0].source_text,
            "https://github.com/acme/tools/pull/8",
        )

    def test_pull_urls_are_deduplicated_and_skip_self(self):
        current = BackendIdentity.github(8, "acme/app")
        references = parse_github_references(
            (
                "https://github.com/acme/app/pull/8 "
                "https://github.com/acme/tools/pull/9 "
                "https://github.com/acme/tools/issues/9 acme/tools#9"
            ),
            default_repo="acme/app",
            current=current,
        )
        self.assertEqual(
            [item.target.stable_id for item in references],
            ["github:acme/tools:9"],
        )

    def test_direct_pull_url_is_not_an_issue_identity(self):
        self.assertIsNone(github_identity("https://github.com/acme/app/pull/8"))

    def test_plain_number_requires_repository_context(self):
        self.assertIsNone(github_identity("123"))
        identity = github_identity("123", default_repo="acme/app")
        self.assertEqual(identity.stable_id, "github:acme/app:123")


if __name__ == "__main__":
    unittest.main()
