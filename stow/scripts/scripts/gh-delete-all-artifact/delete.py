"""Preview and delete selected artifacts."""

from __future__ import annotations

import subprocess
import sys
import time

from util import build_delete_list, fmt_size, load_data


def preview_delete(
    data_path: str,
    selected_names: set[str],
    age_filter: bool,
    age_days: int,
) -> list[tuple[str, int, str]]:
    data = load_data(data_path)
    to_delete = build_delete_list(data, selected_names, age_filter)

    print(f"Will delete {len(to_delete)} artifact(s) from {len(selected_names)} repository/repositories.")
    if age_filter:
        print(f"Filter: artifacts older than {age_days} days only.")
    else:
        print("Filter: all artifacts (no age limit).")
    print()

    for repo_name, art_id, art_name in to_delete[:20]:
        print(f"  - {repo_name} #{art_id} ({art_name})")
    if len(to_delete) > 20:
        print(f"  ... and {len(to_delete) - 20} more")
    print()

    return to_delete


def confirm_and_delete(
    data_path: str,
    selected_names: set[str],
    age_filter: bool,
    age_days: int,
    *,
    input_func=input,
    sleep_func=time.sleep,
) -> int:
    to_delete = preview_delete(data_path, selected_names, age_filter, age_days)
    if not to_delete:
        print("Nothing to delete with the current filter.")
        return 0

    confirm = input_func("Type 'yes' to delete: ").strip()
    if confirm != "yes":
        print("Aborted.")
        return 0

    total = len(to_delete)
    deleted = 0
    failed = 0
    print(f"Deleting {total} artifact(s)...")

    for n, (repo, art_id, _name) in enumerate(to_delete, 1):
        print(f"  [{n}/{total}] Deleting {repo} #{art_id} ... ", end="", flush=True)
        try:
            subprocess.run(
                ["gh", "api", "-X", "DELETE", f"/repos/{repo}/actions/artifacts/{art_id}"],
                check=True,
                capture_output=True,
                text=True,
            )
            print("ok")
            deleted += 1
        except subprocess.CalledProcessError:
            print("failed")
            failed += 1
        sleep_func(0.3)

    print()
    print(f"Done. Deleted: {deleted}, failed: {failed}")
    return 1 if failed else 0
