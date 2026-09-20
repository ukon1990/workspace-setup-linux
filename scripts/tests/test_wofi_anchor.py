import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[2] / "stow/scripts/scripts"
sys.path.insert(0, str(SCRIPTS))
import wofi_anchor  # noqa: E402


class WofiAnchorTests(unittest.TestCase):
    def setUp(self):
        self.anchor = wofi_anchor.DropdownAnchor(
            x=1800,
            y=20,
            area_x=0,
            area_y=48,
            area_width=1920,
            area_height=1032,
        )

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
        self.assertEqual(
            wofi_anchor.clamp_to_area(100, 100, 2000, 520, 0, 0, 1920, 1080),
            (0, 100, 520),
        )

    def test_dropdown_is_centered_under_click_and_below_bar(self):
        self.assertEqual(
            wofi_anchor.dropdown_position(self.anchor, 320, 520),
            (1600, 48),
        )

    def test_cursor_anchor_uses_monitor_reserved_area(self):
        monitors = [
            {
                "x": 1000,
                "y": -200,
                "width": 1920,
                "height": 1080,
                "reserved": [10, 48, 20, 30],
            }
        ]
        with patch.object(
            wofi_anchor,
            "_run_json",
            side_effect=[{"x": 1800, "y": -180}, monitors],
        ):
            anchor = wofi_anchor.cursor_anchor()
        self.assertEqual(
            anchor,
            wofi_anchor.DropdownAnchor(1800, -180, 1010, -152, 1890, 1002),
        )

    @patch.object(wofi_anchor, "_run_json", return_value=None)
    def test_cursor_anchor_gracefully_handles_missing_hyprland(self, _run_json):
        self.assertIsNone(wofi_anchor.cursor_anchor())

    def test_cursor_anchor_uses_logical_dimensions_on_scaled_monitor(self):
        monitor = {
            "x": 1920,
            "y": 0,
            "width": 3840,
            "height": 2160,
            "scale": 2,
            "reserved": [0, 48, 0, 0],
        }
        with patch.object(
            wofi_anchor,
            "_run_json",
            side_effect=[{"x": 2500, "y": 20}, [monitor]],
        ):
            anchor = wofi_anchor.cursor_anchor()
        self.assertEqual(
            anchor,
            wofi_anchor.DropdownAnchor(2500, 20, 1920, 48, 1920, 1032),
        )

    def test_wofi_menu_args_are_case_insensitive_normal_windows(self):
        self.assertEqual(
            wofi_anchor.wofi_menu_args(320, 520),
            [
                "--insensitive",
                "--normal-window",
                "--width",
                "320",
                "--height",
                "520",
                "--define",
                "close_on_focus_loss=true",
            ],
        )

    @patch.object(wofi_anchor.time, "sleep")
    @patch.object(
        wofi_anchor,
        "_run_json",
        side_effect=[[], [{"pid": 42, "size": [320, 520]}]],
    )
    def test_mapped_client_retries_until_pid_appears(self, _run_json, sleep):
        self.assertEqual(
            wofi_anchor._mapped_client(42),
            {"pid": 42, "size": [320, 520]},
        )
        sleep.assert_called_once_with(wofi_anchor.MAP_RETRY_SECONDS)

    @patch.object(wofi_anchor.subprocess, "run")
    @patch.object(
        wofi_anchor,
        "_mapped_client",
        return_value={"pid": 42, "size": [320, 520]},
    )
    def test_position_window_targets_spawned_pid(self, _mapped_client, run):
        wofi_anchor._position_window(42, self.anchor)
        run.assert_called_once_with(
            [
                "hyprctl",
                "dispatch",
                "hl.dsp.window.move({ x = 1600, y = 48, window = 'pid:42' })",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )

    @patch.object(wofi_anchor, "_position_window")
    @patch.object(wofi_anchor, "cursor_anchor")
    @patch.object(wofi_anchor.subprocess, "Popen")
    def test_run_wofi_menu_positions_and_returns_choice(self, popen, cursor_anchor, position):
        cursor_anchor.return_value = self.anchor
        process = MagicMock(pid=42)
        stdin = process.stdin
        process.communicate.return_value = ("Chosen\n", "")
        popen.return_value = process

        result = wofi_anchor.run_wofi_menu(
            ["wofi", "--dmenu", "--normal-window"], input_text="a\nb"
        )

        self.assertEqual(result, "Chosen")
        stdin.write.assert_called_once_with("a\nb")
        stdin.close.assert_called_once_with()
        position.assert_called_once_with(42, self.anchor)

    @patch.object(wofi_anchor, "_position_window")
    @patch.object(wofi_anchor, "cursor_anchor")
    @patch.object(wofi_anchor.subprocess, "Popen")
    def test_run_wofi_menu_reuses_supplied_anchor(self, popen, cursor_anchor, position):
        process = MagicMock(pid=42)
        process.communicate.return_value = ("", "")
        popen.return_value = process

        wofi_anchor.run_wofi_menu(["wofi", "--normal-window"], anchor=self.anchor)

        cursor_anchor.assert_not_called()
        position.assert_called_once_with(42, self.anchor)

    @patch.object(wofi_anchor, "cursor_anchor", return_value=None)
    @patch.object(wofi_anchor.subprocess, "Popen")
    def test_run_wofi_menu_still_runs_without_anchor(self, popen, _cursor_anchor):
        process = MagicMock(pid=42)
        process.communicate.return_value = ("Chosen\n", "")
        popen.return_value = process

        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi"]), "Chosen")

    @patch.object(wofi_anchor, "_position_window")
    @patch.object(wofi_anchor, "cursor_anchor")
    @patch.object(wofi_anchor.subprocess, "Popen")
    def test_layer_shell_menu_skips_click_positioning(self, popen, cursor_anchor, position):
        process = MagicMock(pid=42)
        process.communicate.return_value = ("Chosen\n", "")
        popen.return_value = process

        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi", "--dmenu"]), "Chosen")
        cursor_anchor.assert_not_called()
        position.assert_not_called()

    @patch.object(wofi_anchor, "cursor_anchor", return_value=None)
    @patch.object(wofi_anchor.subprocess, "Popen")
    def test_run_wofi_menu_kills_timed_out_process(self, popen, _cursor_anchor):
        process = MagicMock(pid=42)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("wofi", 0.01),
            ("", ""),
        ]
        popen.return_value = process

        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi"], timeout=0.01), "")
        self.assertEqual(process.communicate.call_count, 2)
        process.kill.assert_called_once_with()

    @patch.object(wofi_anchor, "cursor_anchor", return_value=None)
    @patch.object(wofi_anchor.subprocess, "Popen", side_effect=FileNotFoundError)
    def test_run_wofi_menu_returns_empty_string_when_missing(self, _popen, _cursor_anchor):
        self.assertEqual(wofi_anchor.run_wofi_menu(["wofi"]), "")


if __name__ == "__main__":
    unittest.main()
