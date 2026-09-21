"""Tests for offline PR review draft persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tasks.review_drafts import (
    DraftComment,
    ReviewDraft,
    add_draft_comment,
    clear_draft,
    get_draft,
    load_drafts,
    save_drafts,
    set_draft_body,
)
from tasks.tui.diff_view import merge_draft_rows
from tasks.pulls import parse_diff_rows


class ReviewDraftStoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drafts.yaml"
            draft = ReviewDraft(
                stable_id="github-pr:o/r:1",
                body="overall",
                comments=[
                    DraftComment(
                        path="a.py",
                        side="RIGHT",
                        line=4,
                        body="fix me",
                        start_line=2,
                        created_at="2026-01-01T00:00:00Z",
                    )
                ],
            )
            save_drafts({draft.stable_id: draft}, path)
            loaded = load_drafts(path)
            self.assertIn(draft.stable_id, loaded)
            got = loaded[draft.stable_id]
            self.assertEqual(got.body, "overall")
            self.assertEqual(len(got.comments), 1)
            self.assertEqual(got.comments[0].path, "a.py")
            self.assertEqual(got.comments[0].start_line, 2)
            self.assertEqual(got.count_for_path("a.py"), 1)
            self.assertEqual(got.count_for_path("other.py"), 0)

    def test_add_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "drafts.yaml"
            sid = "github-pr:o/r:9"
            add_draft_comment(
                sid,
                DraftComment(path="x.py", side="LEFT", line=3, body="bye"),
                path,
            )
            set_draft_body(sid, "review note", path)
            draft = get_draft(sid, path)
            self.assertEqual(draft.body, "review note")
            self.assertEqual(len(draft.comments), 1)
            clear_draft(sid, path)
            self.assertEqual(get_draft(sid, path).comments, [])
            self.assertEqual(get_draft(sid, path).body, "")


class DraftMergeTests(unittest.TestCase):
    def test_merge_draft_rows_under_anchor(self) -> None:
        patch = """\
@@ -1,2 +1,2 @@
 context
-old
+new
"""
        rows = parse_diff_rows(patch)
        drafts = [
            DraftComment(path="f.py", side="RIGHT", line=2, body="please fix\nthanks")
        ]
        merged = merge_draft_rows(rows, drafts)
        kinds = [row.kind for row in merged]
        self.assertIn("draft", kinds)
        texts = [row.raw for row in merged if row.kind == "draft"]
        self.assertTrue(any(raw.startswith("◇ draft") for raw in texts))
        self.assertIn("please fix", texts)
        self.assertIn("thanks", texts)


if __name__ == "__main__":
    unittest.main()
