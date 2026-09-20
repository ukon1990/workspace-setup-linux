import subprocess
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import window_size


class WindowSizeTests(unittest.TestCase):
    def setUp(self):
        self.window = {
            "address": "0xabc123",
            "at": [3200, 100],
            "size": [800, 600],
            "monitor": 7,
        }
        self.monitor = {
            "id": 7,
            "x": 2560,
            "y": -200,
            "width": 1920,
            "height": 1080,
            "reserved": [10, 40, 20, 30],
        }

    def test_all_requested_labels_resolve(self):
        self.assertEqual(len(window_size.OPTIONS), 12)
        self.assertEqual(window_size.OPTIONS[0].label, "Tiled · 1/4")
        self.assertEqual(window_size.OPTIONS[6].label, "Float · 1/4")
        tiled = window_size.resolve_option("2/4", self.window, self.monitor)
        floating = window_size.resolve_option("float:1/2", self.window, self.monitor)
        self.assertEqual(tiled.fraction, Fraction(1, 2))
        self.assertFalse(tiled.floating)
        self.assertEqual(floating.fraction, Fraction(1, 2))
        self.assertTrue(floating.floating)

    def test_floating_geometry_uses_reserved_work_area_and_keeps_position(self):
        geometry = window_size.calculate_floating_geometry(
            self.window, self.monitor, Fraction(1, 2)
        )
        self.assertEqual(
            geometry,
            window_size.Geometry(x=3200, y=-160, width=945, height=1010),
        )

    def test_geometry_clamps_both_horizontal_edges(self):
        left_window = {**self.window, "at": [1000, 0]}
        right_window = {**self.window, "at": [4400, 0]}
        self.assertEqual(
            window_size.calculate_floating_geometry(left_window, self.monitor, Fraction(1, 4)).x,
            2570,
        )
        self.assertEqual(
            window_size.calculate_floating_geometry(right_window, self.monitor, Fraction(1, 4)).x,
            3988,
        )

    def test_geometry_rejects_invalid_work_area(self):
        monitor = {**self.monitor, "reserved": [1000, 0, 1000, 0]}
        with self.assertRaisesRegex(window_size.WindowSizeError, "no usable work area"):
            window_size.calculate_floating_geometry(self.window, monitor, Fraction(1, 2))

    def test_overlay_menu_is_centered_and_clamped_to_work_area(self):
        command = window_size.menu_command("overlay", self.window, self.monitor)
        self.assertIn("--global-coords", command)
        self.assertEqual(command[command.index("--xoffset") + 1], "3440")
        self.assertEqual(command[command.index("--yoffset") + 1], "140")
        self.assertEqual(command[command.index("--height") + 1], "520")

    @patch("window_size.run_json")
    def test_cursor_position_parses_hyprctl_output(self, run_json):
        run_json.return_value = {"x": 100, "y": 200}
        self.assertEqual(window_size.cursor_position(), (100, 200))
        run_json.assert_called_once_with(["hyprctl", "-j", "cursorpos"])

    @patch("window_size.run_json")
    def test_cursor_position_rejects_invalid_output(self, run_json):
        run_json.return_value = {"x": "nan"}
        with self.assertRaisesRegex(window_size.WindowSizeError, "invalid cursor position"):
            window_size.cursor_position()

    def test_monitor_at_finds_containing_monitor(self):
        other = {**self.monitor, "id": 2, "x": 0, "y": 0, "width": 1920, "height": 1080}
        found = window_size.monitor_at([other, self.monitor], 3000, 0, other)
        self.assertEqual(found["id"], 7)

    def test_monitor_at_falls_back_to_default_outside_all_monitors(self):
        found = window_size.monitor_at([self.monitor], 999999, 999999, self.monitor)
        self.assertEqual(found, self.monitor)

    @patch("window_size.run_json")
    def test_menu_is_anchored_below_cursor(self, run_json):
        run_json.side_effect = [{"x": 3500, "y": 50}, [self.monitor]]
        command = window_size.menu_command("menu", self.window, self.monitor)
        self.assertIn("--global-coords", command)
        self.assertEqual(command[command.index("--xoffset") + 1], "3340")
        self.assertEqual(command[command.index("--yoffset") + 1], "62")
        self.assertEqual(command[command.index("--height") + 1], "520")

    @patch("window_size.run_json")
    def test_menu_is_clamped_near_monitor_edges(self, run_json):
        run_json.side_effect = [{"x": 4400, "y": 800}, [self.monitor]]
        command = window_size.menu_command("menu", self.window, self.monitor)
        self.assertEqual(command[command.index("--xoffset") + 1], "4140")
        self.assertEqual(command[command.index("--yoffset") + 1], "330")

    @patch("window_size.run_json")
    def test_active_window_matches_monitor_id(self, run_json):
        other = {**self.monitor, "id": 2}
        run_json.side_effect = [self.window, [other, self.monitor]]
        self.assertEqual(window_size.active_window_and_monitor(), (self.window, self.monitor))

    @patch("window_size.run_json")
    def test_active_window_errors_are_explicit(self, run_json):
        run_json.return_value = {}
        with self.assertRaisesRegex(window_size.WindowSizeError, "No focused window"):
            window_size.active_window_and_monitor()

    @patch("window_size.run_json")
    def test_missing_window_monitor_is_explicit(self, run_json):
        run_json.side_effect = [self.window, [{**self.monitor, "id": 3}]]
        with self.assertRaisesRegex(window_size.WindowSizeError, "Monitor 7"):
            window_size.active_window_and_monitor()

    @patch("window_size.run")
    def test_invalid_hyprctl_json_is_explicit(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "not json", "")
        with self.assertRaisesRegex(window_size.WindowSizeError, "invalid JSON"):
            window_size.run_json(["hyprctl", "-j", "activewindow"])

    @patch("window_size.run")
    def test_apply_floating_targets_captured_address(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")
        option = window_size.SizeOption("Float · 1/2", Fraction(1, 2), True)
        window_size.apply_option("0xabc123", option, self.window, self.monitor)
        selector = "address:0xabc123"
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        f"hl.dsp.window.float({{ action = 'set', window = '{selector}' }})",
                    ]
                ),
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        (f"hl.dsp.window.resize({{ x = 945, y = 1010, window = '{selector}' }})"),
                    ]
                ),
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        (f"hl.dsp.window.move({{ x = 3200, y = -160, window = '{selector}' }})"),
                    ]
                ),
            ],
        )

    @patch("window_size.window_by_address")
    @patch("window_size.run")
    def test_apply_tiled_unfloats_and_resizes_group_horizontally(self, run, window_by_address):
        run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")
        window_by_address.side_effect = [
            {"size": [700, 400]},
            {"size": [720, 400]},
            {"size": [945, 400]},
        ]
        option = window_size.SizeOption("Tiled · 1/2", Fraction(1, 2), False)
        window_size.apply_option("0xabc123", option, self.window, self.monitor)
        selector = "address:0xabc123"
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        f"hl.dsp.window.float({{ action = 'unset', window = '{selector}' }})",
                    ]
                ),
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        (
                            "hl.dsp.window.resize({ "
                            f"x = 20, y = 0, relative = true, window = '{selector}'"
                            " })"
                        ),
                    ]
                ),
                call(
                    [
                        "hyprctl",
                        "dispatch",
                        (
                            "hl.dsp.window.resize({ "
                            f"x = 225, y = 0, relative = true, window = '{selector}'"
                            " })"
                        ),
                    ]
                ),
            ],
        )

    @patch("window_size.window_width", side_effect=[700, 680, 945])
    @patch("window_size.run")
    def test_tiled_resize_detects_reversed_split_direction(self, run, _window_width):
        run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")
        window_size.resize_tiled("0xabc123", 945)
        self.assertIn("x = 20", run.call_args_list[0].args[0][2])
        self.assertIn("x = -265", run.call_args_list[1].args[0][2])

    @patch("window_size.window_width", side_effect=[700, 720, 900, 900])
    @patch("window_size.run")
    def test_tiled_resize_accepts_layout_limit(self, run, _window_width):
        run.return_value = subprocess.CompletedProcess([], 0, "ok\n", "")
        window_size.resize_tiled("0xabc123", 945)
        self.assertEqual(run.call_count, 3)

    @patch("window_size.run")
    def test_apply_option_surfaces_dispatch_failure(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "bad selector")
        with self.assertRaisesRegex(window_size.WindowSizeError, "bad selector"):
            window_size.apply_option(
                "0xabc123",
                window_size.SizeOption("Float · 1/2", Fraction(1, 2), True),
                self.window,
                self.monitor,
            )

    @patch("window_size.shutil.which", return_value="/usr/bin/wofi")
    @patch("window_size.run_json")
    @patch("window_size.run")
    def test_menu_cancellation_is_noop(self, run, run_json, _which):
        run_json.side_effect = [{"x": 3500, "y": 50}, [self.monitor]]
        run.return_value = subprocess.CompletedProcess([], 1, "", "")
        self.assertIsNone(window_size.choose_option("menu", self.window, self.monitor))

    @patch("window_size.shutil.which", return_value="/usr/bin/wofi")
    @patch("window_size.run_json")
    @patch("window_size.run")
    def test_menu_maps_selection(self, run, run_json, _which):
        run_json.side_effect = [{"x": 3500, "y": 50}, [self.monitor]]
        run.return_value = subprocess.CompletedProcess([], 0, "Float · 2/3\n", "")
        selected = window_size.choose_option("menu", self.window, self.monitor)
        self.assertEqual(selected.fraction, Fraction(2, 3))
        self.assertTrue(selected.floating)

    @patch("window_size.shutil.which", return_value=None)
    def test_missing_wofi_is_explicit(self, _which):
        with self.assertRaisesRegex(window_size.WindowSizeError, "wofi is not installed"):
            window_size.choose_option("menu", self.window, self.monitor)

    def test_invalid_window_address_is_rejected(self):
        for address in ("", "0x", "class:kitty", "0x123' }"):
            with self.subTest(address=address):
                with self.assertRaisesRegex(window_size.WindowSizeError, "invalid window address"):
                    window_size.lua_selector(address)


if __name__ == "__main__":
    unittest.main()
