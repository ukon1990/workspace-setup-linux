"""Launch the disk browser or print its help without importing Textual."""

import argparse
import os
import shutil
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="disks.sh", description="Interactive Linux data-disk mounting and boot setup."
    )
    parser.parse_args()
    if sys.platform != "linux":
        parser.exit(1, "disks is Linux-only (ntfs3, util-linux, and systemd).\n")
    if os.geteuid() == 0:
        parser.exit(1, "Run disks.sh as your regular user. It prompts for sudo when needed.\n")
    missing = [
        name
        for name in ("lsblk", "findmnt", "mount", "umount", "sudo", "systemctl")
        if not shutil.which(name)
    ]
    if missing:
        parser.exit(1, f"Missing dependencies: {', '.join(missing)}\n")
    from .tui import DisksApp

    DisksApp().run()


if __name__ == "__main__":
    main()
