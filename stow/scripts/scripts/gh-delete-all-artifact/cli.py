#!/usr/bin/env python3
"""CLI entry point for GitHub Actions artifact cleanup."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

# Allow running as a script from the package directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collect import collect
from delete import confirm_and_delete
from overview import print_overview
from tui import run as run_tui


def gh_user() -> str:
    return subprocess.check_output(["gh", "api", "user", "--jq", ".login"], text=True).strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect, review, and selectively delete GitHub Actions artifacts.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all writable repos (orgs, collaborators)",
    )
    parser.add_argument(
        "--owner",
        metavar="LOGIN",
        help="Only repos owned by LOGIN",
    )
    parser.add_argument(
        "--age-days",
        type=int,
        default=7,
        help="Age threshold for the default delete filter (default: 7)",
    )
    return parser.parse_args(argv)


def resolve_filter_mode(args: argparse.Namespace) -> tuple[str, str]:
    if args.owner:
        return "owner", args.owner
    if args.all:
        return "all", ""
    return "mine", ""


def scope_message(filter_mode: str, owner_filter: str) -> str:
    if filter_mode == "all":
        return "all writable repositories"
    if filter_mode == "owner":
        return f"repositories owned by {owner_filter}"
    return "your repositories only"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    filter_mode, owner_filter = resolve_filter_mode(args)

    try:
        subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: not logged in to GitHub CLI. Run: gh auth login", file=sys.stderr)
        return 1

    user = gh_user()
    data_file = tempfile.NamedTemporaryFile(
        prefix="gh-artifacts.",
        suffix=".json",
        delete=False,
    )
    data_path = data_file.name
    data_file.close()

    try:
        print(f"Collecting artifacts ({scope_message(filter_mode, owner_filter)}, logged in as {user})...")
        print()
        try:
            collect(user, data_path, args.age_days, filter_mode, owner_filter)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print_overview(data_path, args.age_days)

        selection = run_tui(data_path, args.age_days)
        if selection is None:
            return 0

        selected_names, age_filter = selection
        return confirm_and_delete(
            data_path,
            selected_names,
            age_filter,
            args.age_days,
        )
    finally:
        if os.path.exists(data_path):
            os.remove(data_path)


if __name__ == "__main__":
    raise SystemExit(main())
