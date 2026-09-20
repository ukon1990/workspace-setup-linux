import importlib.util
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

THEME_PATH = Path(__file__).resolve().parents[1] / "bin" / "theme"
LOADER = SourceFileLoader("theme_cli", str(THEME_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
theme = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = theme
LOADER.exec_module(theme)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.palette = theme.Palette(
            name="test-dark",
            display_name="Test Dark",
            mode="dark",
            icon="",
            colors={
                "bg": "#010101",
                "surface": "#111111",
                "surface_high": "#222222",
                "surface_higher": "#333333",
                "outline": "#444444",
                "text": "#eeeeee",
                "text_muted": "#bbbbbb",
                "primary": "#ff8800",
                "primary_container": "#663300",
                "on_primary": "#ffffff",
                "accent_container": "#553300",
                "hypr_active_border": "#ff8800",
                "hypr_inactive_border": "#444444",
                "shadow": "#000000",
                "groupbar_active": "#663300",
                "groupbar_inactive": "#111111",
                "groupbar_locked_active": "#774400",
                "groupbar_locked_inactive": "#222222",
                "groupbar_text_active": "#ffffff",
                "groupbar_text_inactive": "#bbbbbb",
            },
        )

    def test_wofi_style_uses_palette_colors(self):
        style = theme.render_wofi(self.palette)
        self.assertIn("theme: test-dark (Test Dark)", style)
        self.assertIn("background-color: rgba(17, 17, 17, 0.98)", style)
        self.assertIn("background-color: #663300", style)
        self.assertIn("color: #ffffff", style)
        self.assertIn("border-color: #ff8800", style)

    def test_apply_theme_writes_wofi_style(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "HYPR_THEME_FILE": root / "hypr" / "theme.lua",
                "HYPRLOCK_COLORS_FILE": root / "hypr" / "hyprlock-colors.conf",
                "WAYBAR_COLORS_FILE": root / "waybar" / "colors.css",
                "WOFI_STYLE_FILE": root / "wofi" / "style.css",
                "MAKO_CONFIG_FILE": root / "mako" / "config",
                "SWAPPY_CONFIG_FILE": root / "swappy" / "config",
                "STATE_DIR": root / "themes" / "state",
                "STATE_FILE": root / "themes" / "state" / "current",
            }
            with (
                patch.multiple(theme, **paths),
                patch.object(theme, "load_palette", return_value=self.palette),
            ):
                theme.apply_theme("test-dark", reload=False, quiet=True)

            style = paths["WOFI_STYLE_FILE"].read_text()
            self.assertIn("#entry:selected", style)
            self.assertIn("#663300", style)
            self.assertEqual(paths["STATE_FILE"].read_text(), "test-dark\n")

    def test_find_picker_delegates_wofi_anchoring_to_shared_helper(self):
        with (
            patch.object(theme.shutil, "which", side_effect=lambda c: c == "wofi" and "/usr/bin/wofi"),
            patch.object(
                theme.wofi_anchor,
                "wofi_menu_args",
                return_value=[
                    "--insensitive",
                    "--normal-window",
                    "--define",
                    "close_on_focus_loss=true",
                ],
            ) as wofi_menu_args,
        ):
            command = theme._find_picker()
        wofi_menu_args.assert_called_once_with(theme.PICKER_WIDTH, theme.PICKER_HEIGHT)
        self.assertEqual(
            command[-4:],
            ["--insensitive", "--normal-window", "--define", "close_on_focus_loss=true"],
        )


if __name__ == "__main__":
    unittest.main()
