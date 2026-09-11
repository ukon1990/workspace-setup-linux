"""Collect artifact metadata from GitHub."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime

from util import (
    affiliation_for_mode,
    age_cutoff,
    gh_json,
    progress_bar,
    save_data,
    scope_label,
)


def parse_artifacts(raw_artifacts: list[dict], cutoff: datetime) -> tuple[list[dict], int, int, int]:
    parsed: list[dict] = []
    total_size = 0
    old_count = 0
    old_size = 0

    for art in raw_artifacts:
        created = datetime.fromisoformat(art["created_at"].replace("Z", "+00:00"))
        size = int(art.get("size_in_bytes") or 0)
        is_old = created < cutoff
        parsed.append(
            {
                "id": art["id"],
                "name": art.get("name", ""),
                "size_in_bytes": size,
                "created_at": art["created_at"],
                "is_old": is_old,
            }
        )
        total_size += size
        if is_old:
            old_count += 1
            old_size += size

    return parsed, total_size, old_count, old_size


def fetch_artifacts(full_name: str) -> list[dict]:
    try:
        pages = gh_json(
            "api",
            f"/repos/{full_name}/actions/artifacts",
            "--paginate",
            "--slurp",
        )
    except Exception:
        return []

    artifacts: list[dict] = []
    for page in pages:
        if isinstance(page, dict) and "artifacts" in page:
            artifacts.extend(page["artifacts"])
        elif isinstance(page, list):
            for entry in page:
                if isinstance(entry, dict) and "artifacts" in entry:
                    artifacts.extend(entry["artifacts"])
    return artifacts


def filter_writable_repos(
    repos: list[dict],
    user: str,
    filter_mode: str,
    owner_filter: str,
) -> list[dict]:
    writable = [
        r
        for r in repos
        if r.get("permissions", {}).get("admin") or r.get("permissions", {}).get("push")
    ]

    if filter_mode == "mine":
        return [r for r in writable if r["owner"]["login"] == user]

    if filter_mode == "owner":
        if not owner_filter:
            raise ValueError("--owner requires a login name")
        filtered = [r for r in writable if r["owner"]["login"] == owner_filter]
        if not filtered:
            raise ValueError(f"no writable repositories found for owner '{owner_filter}'")
        return filtered

    return writable


def collect(
    user: str,
    outfile: str,
    age_limit_days: int,
    filter_mode: str,
    owner_filter: str = "",
) -> dict:
    cutoff = age_cutoff(age_limit_days)
    affiliation = affiliation_for_mode(filter_mode)

    repos = gh_json(
        "api",
        f"/user/repos?affiliation={affiliation}&per_page=100",
        "--paginate",
        "--slurp",
    )
    if isinstance(repos, list) and repos and isinstance(repos[0], list):
        repos = [r for page in repos for r in page]

    writable = filter_writable_repos(repos, user, filter_mode, owner_filter)
    repo_data: list[dict] = []
    scanned = len(writable)

    for i, repo in enumerate(writable, 1):
        full_name = repo["full_name"]
        owner = repo["owner"]["login"]
        is_mine = owner == user
        progress_bar(i, scanned, full_name)

        artifacts = fetch_artifacts(full_name)
        if not artifacts:
            continue

        parsed, total_size, old_count, old_size = parse_artifacts(artifacts, cutoff)
        repo_data.append(
            {
                "full_name": full_name,
                "owner": owner,
                "is_mine": is_mine,
                "artifact_count": len(parsed),
                "total_size": total_size,
                "old_count": old_count,
                "old_size": old_size,
                "artifacts": parsed,
            }
        )

    if scanned:
        sys.stderr.write("\n")
        sys.stderr.flush()

    repo_data.sort(key=lambda r: (not r["is_mine"], -r["total_size"], r["full_name"].lower()))

    by_owner: dict[str, dict] = defaultdict(
        lambda: {"repos": 0, "artifacts": 0, "size": 0, "is_mine": False}
    )
    for repo in repo_data:
        entry = by_owner[repo["owner"]]
        entry["repos"] += 1
        entry["artifacts"] += repo["artifact_count"]
        entry["size"] += repo["total_size"]
        entry["is_mine"] = repo["is_mine"]

    owner_summary = sorted(
        (
            {
                "owner": owner,
                "is_mine": stats["is_mine"],
                "repos": stats["repos"],
                "artifacts": stats["artifacts"],
                "size": stats["size"],
            }
            for owner, stats in by_owner.items()
        ),
        key=lambda x: (not x["is_mine"], -x["size"], x["owner"].lower()),
    )

    payload = {
        "user": user,
        "filter_mode": filter_mode,
        "filter_label": scope_label(filter_mode, owner_filter),
        "scanned_repos": scanned,
        "repos_with_artifacts": len(repo_data),
        "total_artifacts": sum(r["artifact_count"] for r in repo_data),
        "total_size": sum(r["total_size"] for r in repo_data),
        "owner_summary": owner_summary,
        "repos": repo_data,
    }
    save_data(outfile, payload)
    return payload
