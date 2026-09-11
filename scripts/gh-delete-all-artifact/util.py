"""Shared helpers for GitHub artifact cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any


def fmt_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def progress_bar(current: int, total: int, label: str, width: int = 30) -> None:
    if total <= 0:
        return
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = 100 * current / total
    short = label if len(label) <= 36 else label[:33] + "..."
    sys.stderr.write(
        f"\r  [{bar}] {current:>{len(str(total))}}/{total} ({pct:5.1f}%)  {short:<36}"
    )
    sys.stderr.flush()


def gh_json(*args: str) -> Any:
    out = subprocess.check_output(["gh", *args], text=True)
    if not out.strip():
        return []
    data = json.loads(out)
    if isinstance(data, list) and data and isinstance(data[0], list):
        return [item for page in data for item in page]
    return data


def age_cutoff(age_limit_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=age_limit_days)


def load_data(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_data(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def affiliation_for_mode(filter_mode: str) -> str:
    if filter_mode == "mine":
        return "owner"
    return "owner,collaborator,organization_member"


def scope_label(filter_mode: str, owner_filter: str) -> str:
    labels = {
        "mine": "your repositories only",
        "all": "all writable repositories",
        "owner": f"owner:{owner_filter}",
    }
    return labels[filter_mode]


def compute_delete_totals(
    data: dict[str, Any],
    selected: list[bool],
    age_filter: bool,
) -> tuple[int, int]:
    del_count = 0
    del_size = 0
    for i, repo in enumerate(data["repos"]):
        if not selected[i]:
            continue
        for art in repo["artifacts"]:
            if age_filter and not art["is_old"]:
                continue
            del_count += 1
            del_size += art["size_in_bytes"]
    return del_count, del_size


def build_delete_list(
    data: dict[str, Any],
    selected_names: set[str],
    age_filter: bool,
) -> list[tuple[str, int, str]]:
    to_delete: list[tuple[str, int, str]] = []
    for repo in data["repos"]:
        if repo["full_name"] not in selected_names:
            continue
        for art in repo["artifacts"]:
            if age_filter and not art["is_old"]:
                continue
            to_delete.append((repo["full_name"], art["id"], art["name"]))
    return to_delete
