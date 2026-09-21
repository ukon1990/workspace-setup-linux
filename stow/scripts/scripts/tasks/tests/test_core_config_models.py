import tempfile
import unittest
from pathlib import Path

from tasks.config import ConfigError, load_config
from tasks.models import BackendIdentity, TaskDetail, TaskSummary


class ModelTests(unittest.TestCase):
    def test_github_identity_has_stable_repo_scoped_key(self):
        identity = BackendIdentity.github(12, "Owner/Repo")
        self.assertEqual(identity.stable_id, "github:owner/repo:12")
        self.assertEqual(identity.display_key, "owner/repo#12")

    def test_detail_exposes_summary_identity(self):
        identity = BackendIdentity.jira("proj-7")
        detail = TaskDetail(TaskSummary(identity, "Title", "Open", components=("Platform",)))
        self.assertEqual(detail.identity.stable_id, "jira:PROJ-7")
        self.assertEqual(detail.summary.components, ("Platform",))


class ConfigTests(unittest.TestCase):
    def write_config(self, directory, content):
        path = Path(directory) / "config.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory) / "missing.yaml")
        self.assertEqual(config.jira.limit, 100)
        self.assertEqual(config.github.limit, 100)

    def test_loads_and_normalizes_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(
                directory,
                """
jira:
  default_project: proj
  limit: 25
  jql_extra: labels = cli
github:
  default_repo: Owner/Repo
  limit: 50
  search: label:ready
""",
            )
            config = load_config(path)
        self.assertEqual(config.jira.default_project, "PROJ")
        self.assertEqual(config.github.default_repo, "Owner/Repo")
        self.assertEqual(config.github.search, "label:ready")

    def test_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, "github:\n  token: secret\n")
            with self.assertRaisesRegex(ConfigError, "Unknown github"):
                load_config(path)

    def test_rejects_invalid_limits_and_boolean(self):
        for value in ("0", "1001", "true", '"10"'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = self.write_config(directory, f"jira:\n  limit: {value}\n")
                with self.assertRaisesRegex(ConfigError, "jira.limit"):
                    load_config(path)

    def test_rejects_non_mapping_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, "jira: false\n")
            with self.assertRaisesRegex(ConfigError, "jira must be a mapping"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
