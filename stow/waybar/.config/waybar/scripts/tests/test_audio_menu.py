import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_menu

WPCTL_STATUS = """\
Audio
 ├─ Devices:
 │      45. HDMI Controller                    [alsa]
 │
 ├─ Sinks:
 │      56. Monitor Audio Digital Stereo       [vol: 0.45]
 │  *   57. Headset Analog Stereo              [vol: 1.00]
 │      60. Headset Analog Stereo              [vol: 0.55]
 │
 ├─ Sources:
 │      58. Headset Mono                       [vol: 1.00]
 │  *   59. Webcam Analog Stereo               [vol: 1.00]
 │
 ├─ Filters:
 │
 └─ Streams:
        82. Browser

Video
 ├─ Sources:
 │  *   87. Webcam (V4L2)
"""


class AudioMenuTests(unittest.TestCase):
    def test_parse_devices_reads_requested_section_and_default(self):
        sinks = audio_menu.parse_devices(WPCTL_STATUS, "Sinks")
        sources = audio_menu.parse_devices(WPCTL_STATUS, "Sources")

        self.assertEqual(
            sinks,
            [
                audio_menu.AudioDevice(56, "Monitor Audio Digital Stereo", False),
                audio_menu.AudioDevice(57, "Headset Analog Stereo", True),
                audio_menu.AudioDevice(60, "Headset Analog Stereo", False),
            ],
        )
        self.assertEqual(
            sources,
            [
                audio_menu.AudioDevice(58, "Headset Mono", False),
                audio_menu.AudioDevice(59, "Webcam Analog Stereo", True),
            ],
        )

    def test_device_menu_labels_are_unique_and_mark_default(self):
        first = audio_menu.AudioDevice(57, "Headset", True)
        second = audio_menu.AudioDevice(60, "Headset", False)

        self.assertEqual(first.menu_label, "● Headset  ·  57")
        self.assertEqual(second.menu_label, "○ Headset  ·  60")
        self.assertNotEqual(first.menu_label, second.menu_label)

    def test_parse_devices_rejects_missing_section(self):
        with self.assertRaisesRegex(audio_menu.AudioMenuError, "Sources section"):
            audio_menu.parse_devices("Audio\n ├─ Sinks:\n", "Sources")

    @patch("audio_menu.run")
    def test_audio_devices_reports_wpctl_failure(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "server unavailable\n")

        with self.assertRaisesRegex(audio_menu.AudioMenuError, "server unavailable"):
            audio_menu.audio_devices("Sinks")

    @patch("audio_menu.run")
    def test_audio_devices_reports_empty_section(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "Audio\n ├─ Sinks:\n", "")

        with self.assertRaisesRegex(audio_menu.AudioMenuError, "No output devices"):
            audio_menu.audio_devices("Sinks")

    @patch("audio_menu.wofi_anchor.run_wofi_menu")
    @patch("audio_menu.wofi_anchor.wofi_menu_args")
    @patch("audio_menu.shutil.which", return_value="/usr/bin/wofi")
    def test_choose_delegates_to_shared_wofi_helper(self, _which, menu_args, run_menu):
        menu_args.return_value = ["--normal-window", "--height", "320"]
        run_menu.return_value = "Input devices"

        result = audio_menu.choose("Audio", audio_menu.TOP_LEVEL_OPTIONS)

        self.assertEqual(result, "Input devices")
        menu_args.assert_called_once_with(audio_menu.MENU_WIDTH, audio_menu.MENU_HEIGHT)
        command = run_menu.call_args.args[0]
        self.assertEqual(command[-3:], ["--normal-window", "--height", "320"])
        self.assertNotIn("--dynamic-lines", command)
        self.assertIn("dynamic_lines=true", command)
        self.assertEqual(
            run_menu.call_args.kwargs["input_text"],
            "Output devices\nInput devices\nOpen audio controls",
        )

    @patch("audio_menu.choose")
    @patch("audio_menu.audio_devices")
    def test_choose_device_resolves_the_selected_id(self, audio_devices, choose):
        selected = audio_menu.AudioDevice(60, "Headset", False)
        audio_devices.return_value = [
            audio_menu.AudioDevice(57, "Headset", True),
            selected,
        ]
        choose.return_value = selected.menu_label

        self.assertEqual(audio_menu.choose_device("Sinks"), selected)
        choose.assert_called_once_with(
            "Audio output",
            ["● Headset  ·  57", "○ Headset  ·  60"],
        )

    @patch("audio_menu.wofi_anchor.subprocess.run")
    @patch("audio_menu.audio_devices")
    @patch("audio_menu.shutil.which", return_value="/usr/bin/wofi")
    def test_choose_device_resolves_non_default_through_shared_runner(
        self, _which, audio_devices, run
    ):
        selected = audio_menu.AudioDevice(60, "Headset", False)
        audio_devices.return_value = [
            audio_menu.AudioDevice(57, "Headset", True),
            selected,
        ]
        run.return_value = subprocess.CompletedProcess([], 0, f"{selected.menu_label}\n", "")

        self.assertEqual(audio_menu.choose_device("Sinks"), selected)

    @patch("audio_menu.run")
    def test_set_default_uses_wpctl_device_id(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        audio_menu.set_default(audio_menu.AudioDevice(59, "Webcam", False))
        run.assert_called_once_with(["wpctl", "set-default", "59"])

    @patch("audio_menu.run")
    def test_set_default_reports_failure(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "not found\n")
        with self.assertRaisesRegex(audio_menu.AudioMenuError, "not found"):
            audio_menu.set_default(audio_menu.AudioDevice(999, "Missing", False))

    @patch("audio_menu.subprocess.Popen")
    def test_open_audio_controls_launches_pavucontrol(self, popen):
        audio_menu.open_audio_controls()
        popen.assert_called_once_with(
            ["pavucontrol"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    @patch("audio_menu.set_default")
    @patch("audio_menu.choose_device")
    @patch("audio_menu.choose", side_effect=["Output devices"])
    def test_main_routes_output_selection(self, _choose, choose_device, set_default):
        selected = audio_menu.AudioDevice(57, "Headset", False)
        choose_device.return_value = selected

        self.assertEqual(audio_menu.main(), 0)
        choose_device.assert_called_once_with("Sinks")
        set_default.assert_called_once_with(selected)

    @patch("audio_menu.set_default")
    @patch("audio_menu.choose_device")
    @patch("audio_menu.choose", return_value="Input devices")
    def test_main_does_not_reset_current_default(self, _choose, choose_device, set_default):
        choose_device.return_value = audio_menu.AudioDevice(59, "Webcam", True)

        self.assertEqual(audio_menu.main(), 0)
        choose_device.assert_called_once_with("Sources")
        set_default.assert_not_called()

    @patch("audio_menu.open_audio_controls")
    @patch("audio_menu.choose", return_value="Open audio controls")
    def test_main_opens_audio_controls(self, _choose, open_audio_controls):
        self.assertEqual(audio_menu.main(), 0)
        open_audio_controls.assert_called_once_with()

    @patch("audio_menu.choose", return_value="")
    def test_main_treats_cancellation_as_success(self, _choose):
        self.assertEqual(audio_menu.main(), 0)

    @patch("audio_menu.notify_error")
    @patch("audio_menu.choose", side_effect=audio_menu.AudioMenuError("broken"))
    def test_main_reports_user_facing_errors(self, _choose, notify_error):
        self.assertEqual(audio_menu.main(), 1)
        notify_error.assert_called_once_with("broken")

    @patch("audio_menu.subprocess.run")
    def test_run_forces_stable_locale(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        audio_menu.run(["wpctl", "status"])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()
