#!/usr/bin/env python3
"""Entry point for the app-install command."""

from .cli import run

if __name__ == "__main__":
    raise SystemExit(run())
