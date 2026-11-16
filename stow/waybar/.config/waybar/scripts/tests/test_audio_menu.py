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
                audio_menu.AudioDevice(56, "Monitor Audio Digital Stereo", False, 0.45),
                audio_menu.AudioDevice(57, "Headset Analog Stereo", True, 1.0),
                audio_menu.AudioDevice(60, "Headset Analog Stereo", False, 0.55),
            ],
        )
        self.assertEqual(
            sources,
            [
                audio_menu.AudioDevice(58, "Headset Mono", False, 1.0),
                audio_menu.AudioDevice(59, "Webcam Analog Stereo", True, 1.0),
            ],
        )

    def test_device_row_shows_name_detail_volume_and_default(self):
        device = audio_menu.AudioDevice(57, "Headset Analog Stereo", True, 0.5)
        row = device.row({}).text
        self.assertIn("●  <b>Headset</b>", row)
        self.assertIn("50%", row)
        self.assertIn("analog stereo · default", row)
        muted = audio_menu.AudioDevice(56, "Monitor Audio Digital Stereo", False, 0.45, True)
        self.assertIn("muted", muted.row({}).text)
        self.assertEqual(
            muted.name_and_detail({"Monitor Audio": "Desk monitor"}),
            ("Desk monitor", "Monitor Audio · digital stereo"),
        )

    def test_parse_devices_reads_muted_state(self):
        status = WPCTL_STATUS.replace("[vol: 0.45]", "[vol: 0.45 MUTED]")
        self.assertTrue(audio_menu.parse_devices(status, "Sinks")[0].muted)

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

    DEVICES = [
        audio_menu.AudioDevice(56, "Monitor Audio Digital Stereo", False, 0.45),
        audio_menu.AudioDevice(57, "Headset Analog Stereo", True, 1.0),
    ]

    def run_main(self, *choices):
        """Run main() with the panel answering ``choices`` in order."""
        with (
            patch.object(audio_menu.wofi_anchor, "cursor_anchor", return_value=None),
            patch.object(audio_menu, "audio_devices", return_value=self.DEVICES) as devices,
            patch.object(audio_menu, "choose", side_effect=list(choices)) as choose,
        ):
            return audio_menu.main(), devices, choose

    @patch.object(audio_menu, "set_default")
    def test_main_sets_the_picked_device_as_default(self, set_default):
        result, _, _ = self.run_main(audio_menu.rofi_menu.Choice(0, 0))
        self.assertEqual(result, 0)
        set_default.assert_called_once_with(self.DEVICES[0])

    @patch.object(audio_menu, "set_default")
    def test_main_does_not_reset_current_default(self, set_default):
        self.run_main(audio_menu.rofi_menu.Choice(1, 0))
        set_default.assert_not_called()

    def test_main_flips_between_outputs_and_inputs(self):
        _, devices, choose = self.run_main(
            audio_menu.rofi_menu.Choice(0, 1), audio_menu.rofi_menu.Choice(None, -1)
        )
        self.assertEqual([call.args[0] for call in devices.call_args_list], ["Sinks", "Sources"])
        self.assertEqual([call.args[0] for call in choose.call_args_list], [0, 1])

    @patch.object(audio_menu, "toggle_mute")
    def test_main_mutes_and_reopens(self, toggle_mute):
        _, _, choose = self.run_main(
            audio_menu.rofi_menu.Choice(0, 2), audio_menu.rofi_menu.Choice(None, -1)
        )
        toggle_mute.assert_called_once_with(self.DEVICES[0])
        self.assertEqual(choose.call_count, 2)

    @patch.object(audio_menu, "open_audio_controls")
    def test_main_opens_audio_controls(self, open_audio_controls):
        result, _, _ = self.run_main(audio_menu.rofi_menu.Choice(0, 3))
        self.assertEqual(result, 0)
        open_audio_controls.assert_called_once_with()

    def test_main_treats_cancellation_as_success(self):
        self.assertEqual(self.run_main(audio_menu.rofi_menu.Choice(None, -1))[0], 0)

    @patch.object(audio_menu, "notify_error")
    def test_main_reports_user_facing_errors(self, notify_error):
        with (
            patch.object(audio_menu.wofi_anchor, "cursor_anchor", return_value=None),
            patch.object(audio_menu, "audio_devices", side_effect=audio_menu.AudioMenuError("no")),
        ):
            self.assertEqual(audio_menu.main(), 1)
        notify_error.assert_called_once_with("no")

    @patch("audio_menu.subprocess.run")
    def test_run_forces_stable_locale(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        audio_menu.run(["wpctl", "status"])
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()
