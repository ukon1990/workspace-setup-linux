"""Read, escape, and refresh desktop application entries."""

import re
import shutil
import subprocess


def desktop_read(path):
    result = {}
    active = False
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith("["):
                active = line == "[Desktop Entry]"
            elif active and "=" in line:
                key, value = line.split("=", 1)
                result[key] = value
    return result


def desktop_escape(value):
    return (
        value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )


def desktop_unescape(value):
    return re.sub(
        r"\\([snrt\\])",
        lambda m: {"s": " ", "n": "\n", "r": "\r", "t": "\t", "\\": "\\"}[m[1]],
        value,
    )


def exec_quote(value):
    return '"' + "".join("\\" + c if c in '\\"`$' else "%%" if c == "%" else c for c in value) + '"'


def refresh_desktops(desktops):
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(desktops)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
