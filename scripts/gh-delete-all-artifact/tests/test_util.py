import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from util import (
    affiliation_for_mode,
    build_delete_list,
    compute_delete_totals,
    fmt_size,
    scope_label,
)


class UtilTests(unittest.TestCase):
    def test_fmt_size_bytes(self):
        self.assertEqual(fmt_size(512), "512 B")

    def test_fmt_size_megabytes(self):
        self.assertEqual(fmt_size(5 * 1024 * 1024), "5.0 MB")

    def test_affiliation_for_mode(self):
        self.assertEqual(affiliation_for_mode("mine"), "owner")
        self.assertEqual(affiliation_for_mode("all"), "owner,collaborator,organization_member")

    def test_scope_label(self):
        self.assertEqual(scope_label("mine", ""), "your repositories only")
        self.assertEqual(scope_label("owner", "acme"), "owner:acme")

    def test_compute_delete_totals_with_age_filter(self):
        data = {
            "repos": [
                {
                    "artifacts": [
                        {"is_old": True, "size_in_bytes": 100},
                        {"is_old": False, "size_in_bytes": 50},
                    ]
                }
            ]
        }
        count, size = compute_delete_totals(data, [True], age_filter=True)
        self.assertEqual((count, size), (1, 100))

    def test_build_delete_list(self):
        fixture = os.path.join(os.path.dirname(__file__), "fixtures", "sample_data.json")
        with open(fixture, encoding="utf-8") as fh:
            data = json.load(fh)
        items = build_delete_list(data, {"alice/big-repo"}, age_filter=True)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0], "alice/big-repo")


if __name__ == "__main__":
    unittest.main()
