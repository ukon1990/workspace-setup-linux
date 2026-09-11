"""Command-line parsing and error reporting for kube-status."""

from __future__ import annotations

import argparse
import sys

from .aggregate import aggregate
from .collect import fetch_resources, resolve_context
from .render import render_json, render_terminal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show kubectl pod and workload readiness grouped by namespace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  kube-status\n"
            "  kube-status --json\n"
            "  kube-status --context jonaskf-vps\n"
            "  kube-status --namespace concoctly\n"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of a terminal report",
    )
    parser.add_argument(
        "--context",
        help="kubectl context to query (defaults to current-context)",
    )
    parser.add_argument(
        "--namespace",
        "-n",
        help="Limit to one namespace instead of all namespaces",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    context = resolve_context(args.context)
    collection = fetch_resources(context, namespace=args.namespace)
    status = aggregate(collection)
    if args.json:
        print(render_json(status))
    else:
        print(render_terminal(status))
    if not status.get("available"):
        return 1
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except ValueError as error:
        print(f"kube-status: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130
