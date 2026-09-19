"""Print artifact overview tables."""

from __future__ import annotations

from util import fmt_size, load_data


def print_overview(data_path: str, age_days: int) -> None:
    data = load_data(data_path)
    total_old = sum(r["old_count"] for r in data["repos"])
    total_old_size = sum(r["old_size"] for r in data["repos"])

    print("=" * 72)
    print("GitHub Actions Artifacts Overview")
    print("=" * 72)
    print(f"Logged in as:     {data['user']}")
    print(f"Scope:            {data.get('filter_label', 'all writable repositories')}")
    print(f"Repos scanned:    {data['scanned_repos']}")
    print(f"With artifacts:   {data['repos_with_artifacts']}")
    print(f"Total artifacts:  {data['total_artifacts']}")
    print(f"Total size:       {fmt_size(data['total_size'])}")
    print(f"Older than {age_days}d:  {total_old} artifacts ({fmt_size(total_old_size)})")
    print()

    print("── Summary by owner " + "─" * 49)
    print(f"{'Owner':<28} {'Repos':>6} {'Artifacts':>10} {'Size':>12}")
    print("─" * 72)
    for row in data["owner_summary"]:
        label = row["owner"]
        if row["is_mine"]:
            label += " (you)"
        print(
            f"{label:<28} {row['repos']:>6} {row['artifacts']:>10} "
            f"{fmt_size(row['size']):>12}"
        )
    print("─" * 72)
    print()

    print("── Repositories (yours first, then by size) " + "─" * 27)
    print(f"{'Repository':<42} {'Artifacts':>10} {'Size':>12}  {f'>{age_days}d':>6}")
    print("─" * 72)
    for repo in data["repos"]:
        mine = "*" if repo["is_mine"] else " "
        print(
            f"{mine} {repo['full_name']:<40} {repo['artifact_count']:>10} "
            f"{fmt_size(repo['total_size']):>12}  {repo['old_count']:>6}"
        )
    print("─" * 72)
    print("  * = owned by you")
    print()
