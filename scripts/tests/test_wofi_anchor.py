import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "stow/scripts/scripts"
sys.path.insert(0, str(SCRIPTS))
import wofi_anchor  # noqa: E402


class WofiAnchorTests(unittest.TestCase):
    def test_clamp_to_area_keeps_value_inside_bounds(self):
        self.assertEqual(
            wofi_anchor.clamp_to_area(100, 100, 320, 520, 0, 0, 1920, 1080),
            (100, 100, 520),
        )

    def test_clamp_to_area_clamps_near_edges(self):
        self.assertEqual(
            wofi_anchor.clamp_to_area(1800, 1000, 320, 520, 0, 0, 1920, 1080),
            (1600, 560, 520),
        )

    def test_wofi_menu_args_requests_normal_window_and_close_on_focus_loss(self):
        self.assertEqual(
            wofi_anchor.wofi_menu_args(320, 520),
            [
                "--normal-window",
                "--width",
                "320",
                "--height",
                "520",
                "--define",
                "close_on_focus_loss=true",
            ],
        )

    @patch("wofi_anchor.subprocess.run")
    def test_run_wofi_menu_returns_stripped_choice(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "Chosen\n", "")
        result = wofi_anchor.run_wofi_menu(["wofi", "--dmenu"], input_text="a\nb")
        self.assertEqual(result, "Chosen")
        run.assert_called_once()

    @patch("wofi_anchor.subprocess.run")
    def test_run_wofi_menu_returns_empty_string_when_cancelled(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi", "--dmenu"]), "")

    @patch("wofi_anchor.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="wofi", timeout=30))
    def test_run_wofi_menu_returns_empty_string_on_timeout(self, _run):
        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi", "--dmenu"], timeout=0.01), "")

    @patch("wofi_anchor.subprocess.run", side_effect=FileNotFoundError)
    def test_run_wofi_menu_returns_empty_string_when_missing(self, _run):
        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi", "--dmenu"]), "")


if __name__ == "__main__":
    unittest.main()
