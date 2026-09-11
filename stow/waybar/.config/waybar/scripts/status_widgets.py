#!/usr/bin/env python3
"""Stable command entry point for the independently loaded Waybar widgets."""

import html
import importlib
import json
import sys

from widgets.state import transaction

MODULES = {
    name: (name, name + "_module")
    for name in (
        "cpu",
        "memory",
        "network",
        "disk",
        "gpu",
        "volume",
        "media",
        "hyprsunset",
        "kubernetes",
    )
}
ACTIONS = {
    f"hyprsunset-{name}": ("hyprsunset", f"hyprsunset_{name}")
    for name in ("toggle", "adjust", "reset", "menu", "schedule")
}


def dispatch(command, argv):
    widget, function = (MODULES | ACTIONS)[command]
    handler = getattr(importlib.import_module(f"widgets.{widget}"), function)
    with transaction(widget) as state:
        if command in ACTIONS:
            handler(state, argv)
            return None
        payload = dict(handler(state))
    # Tooltip content is plain text; escape metadata/process names for Pango.
    payload["tooltip"] = html.escape(str(payload.get("tooltip", "")), quote=False)
    return payload


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in MODULES and command not in ACTIONS:
        usage = "Usage: status_widgets.py [" + "|".join([*MODULES, *ACTIONS]) + "]"
        print(json.dumps({"text": "widget?", "tooltip": usage}))
        return 1
    try:
        payload = dispatch(command, sys.argv[2:])
    except Exception as exc:
        print(f"{command}: {exc}", file=sys.stderr)
        if command in MODULES:
            print(
                json.dumps(
                    {
                        "text": "n/a",
                        "tooltip": f"{command}: metrics unavailable",
                        "class": ["metric", "muted"],
                    }
                )
            )
        return 1
    if payload is not None:
        print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
