"""Tests for Markdown image splitting and download helpers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks.images import (
    fetch_image,
    fetch_images,
    markdown_image_urls,
    split_markdown_images,
)


class SplitMarkdownImagesTests(unittest.TestCase):
    def test_splits_inline_images_and_keeps_surrounding_text(self):
        markdown = "Before\n\n![shot](https://example.test/a.png)\n\nAfter"
        segments = split_markdown_images(markdown)
        self.assertEqual(
            [(s.kind, s.text, s.alt, s.url) for s in segments],
            [
                ("text", "Before\n\n", "", ""),
                ("image", "", "shot", "https://example.test/a.png"),
                ("text", "\n\nAfter", "", ""),
            ],
        )

    def test_skips_media_pseudo_urls(self):
        markdown = "![x](media:abc-123)"
        segments = split_markdown_images(markdown)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "text")
        self.assertIn("media:abc-123", segments[0].text)

    def test_markdown_image_urls_dedupes(self):
        markdown = (
            "![a](https://example.test/a.png) "
            "![b](https://example.test/a.png) "
            "![c](https://example.test/c.jpg)"
        )
        self.assertEqual(
            markdown_image_urls(markdown),
            ("https://example.test/a.png", "https://example.test/c.jpg"),
        )


class FetchImagesTests(unittest.TestCase):
    def test_fetch_image_caches_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)

            def fake_urlopen(request, timeout=0):
                class Response:
                    def read(self, _n):
                        return b"\x89PNG\r\n\x1a\n" + b"data"

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return False

                self.assertTrue(
                    request.get_header("Authorization")
                    or request.headers.get("Authorization")
                )
                return Response()

            with patch("tasks.images.urlopen", side_effect=fake_urlopen):
                with patch("tasks.images._github_token", return_value="tok"):
                    path = fetch_image(
                        "https://user-images.githubusercontent.com/1/a.png",
                        cache_dir=cache,
                    )
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())
            first = path.read_bytes()

            with patch("tasks.images.urlopen") as urlopen:
                again = fetch_image(
                    "https://user-images.githubusercontent.com/1/a.png",
                    cache_dir=cache,
                )
                urlopen.assert_not_called()
            self.assertEqual(again, path)
            self.assertEqual(again.read_bytes(), first)

    def test_fetch_images_omits_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with patch("tasks.images.fetch_image", side_effect=[Path("ok"), None]):
                resolved = fetch_images(
                    ["https://example.test/a.png", "https://example.test/b.png"],
                    cache_dir=cache,
                )
            self.assertEqual(list(resolved), ["https://example.test/a.png"])


if __name__ == "__main__":
    unittest.main()
