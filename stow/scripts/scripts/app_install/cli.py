"""Command-line parsing and error reporting."""

import argparse
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from .common import PASSWORD_STORES
from .installation import install_app
from .management import manage_app
from .metadata import edit_app, list_apps


def main():
    parser = argparse.ArgumentParser(
        description="Install locally downloaded application bundles without root privileges.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  app-install ./Something.AppImage --name Something\n"
        "  app-install ./Something.AppImage --update\n"
        "  app-install ./Cursor.AppImage --name Cursor --password-store gnome-libsecret\n"
        "  app-install --rename Something --name Something-1.0\n"
        "  app-install --rename Something    # select an installed app\n"
        "  app-install --uninstall           # select an installed app\n"
        "  app-install --remove --name Something\n"
        "  app-install --list\n"
        '  app-install --edit --name Something --categories "Development;IDE;"\n'
        "  app-install --edit --name Cursor --password-store gnome-libsecret",
    )
    parser.add_argument("archive", type=Path, nargs="?")
    parser.add_argument(
        "--name",
        help="App name (current name for rename/remove); defaults to the archive filename on install",
    )
    parser.add_argument("--icon", type=Path, help="Copy this icon, replacing any saved icon")
    parser.add_argument(
        "--exec",
        dest="executable",
        action="append",
        help="Executable relative to the app root; repeat for ordered fallbacks",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--update", action="store_true", help="Select an installed app of the same type"
    )
    actions.add_argument(
        "--rename",
        metavar="NEW_NAME",
        help="Rename an installed app; --name selects its current name",
    )
    actions.add_argument(
        "--uninstall",
        "--remove",
        action="store_true",
        help="Remove an installed app; omit --name to select from a list",
    )
    actions.add_argument(
        "--list", "-l", action="store_true", help="List managed apps and their categories"
    )
    actions.add_argument(
        "--edit", action="store_true", help="Edit desktop metadata; omit --name to select an app"
    )
    parser.add_argument("--comment", help="Desktop description (with --edit)")
    parser.add_argument("--keywords", help="Semicolon-separated search keywords (with --edit)")
    parser.add_argument(
        "--terminal",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run in a terminal, or --no-terminal (with --edit)",
    )
    parser.add_argument(
        "--password-store",
        metavar="BACKEND",
        help=(
            "Chromium/Electron password-store backend injected into the launcher "
            f"({', '.join(PASSWORD_STORES)}); omit to keep an existing value, "
            "pass an empty string with --edit to clear"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--id", help="Explicit stable launcher identifier (integration)")
    parser.add_argument("--subdir", choices=("apps", "jetbrains"), default="apps")
    parser.add_argument("--categories")
    parser.add_argument("--startup-class")
    parser.add_argument("--preserve-launcher", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ.get("INSTALL_ROOT", "~/.local/opt")).expanduser().resolve()
    bins = Path(os.environ.get("BIN_DIR", "~/.local/bin")).expanduser().resolve()
    desktops = (
        Path(os.environ.get("DESKTOP_DIR", "~/.local/share/applications")).expanduser().resolve()
    )
    edit_values = (
        args.categories,
        args.startup_class,
        args.comment,
        args.keywords,
        args.terminal,
        args.icon,
        args.password_store,
    )
    if args.list or args.edit:
        if (
            args.archive
            or args.executable
            or args.id
            or args.preserve_launcher
            or args.subdir != "apps"
        ):
            parser.error("List/edit does not accept archive or installation options.")
        if args.list:
            if any(value is not None for value in edit_values):
                parser.error("--list accepts only --name and --dry-run.")
            list_apps(args, root, desktops)
        else:
            if all(value is None for value in edit_values):
                parser.error(
                    "--edit requires a metadata option such as --categories, --icon, "
                    "or --password-store."
                )
            edit_app(args, root, bins, desktops)
        return
    if any(value is not None for value in (args.comment, args.keywords, args.terminal)):
        parser.error("--comment, --keywords and --terminal require --edit.")
    if args.rename is not None or args.uninstall:
        if (
            args.archive
            or args.icon
            or args.executable
            or args.id
            or args.categories
            or args.startup_class
            or args.preserve_launcher
            or args.password_store is not None
            or args.subdir != "apps"
        ):
            parser.error("Rename/uninstall accepts only --name and --dry-run alongside the action.")
        manage_app(args, root, bins, desktops)
        return
    if args.archive is None:
        parser.error("An archive is required for install/update.")
    install_app(args, root, bins, desktops)


def run():
    """Translate expected CLI failures into concise diagnostics and exit codes."""
    try:
        main()
    except (ValueError, OSError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(f"app-install: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130
    return 0
