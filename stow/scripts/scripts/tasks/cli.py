"""Command-line integration for the read-only tasks browser."""

from __future__ import annotations

import argparse
import re
import sys
from typing import TYPE_CHECKING, Optional, Sequence

from .config import ConfigError, TasksConfig, load_config
from .filters import (
    AssigneeFilter,
    WorkFilter,
    clear_assignee_filter,
    clear_work_filter,
    load_assignee_filter,
    load_work_filter,
    save_assignee_filter,
    save_work_filter,
)
from .github import GithubBackend, GithubError
from .jira import JiraBackend, JiraError
from .launcher import load_recent_backend, save_recent_backend
from .models import Backend, BackendIdentity, TaskDetail, TaskSummary
from .pulls import GithubPullsBackend, resolve_github_repository
from .references import github_identity, jira_identity

if TYPE_CHECKING:
    from .tui import TaskBackend


class JiraTuiBackend:
    backend_label = "Jira"

    def __init__(
        self,
        backend: JiraBackend,
        project: str,
        *,
        limit: Optional[int] = None,
        jql_extra: Optional[str] = None,
    ) -> None:
        self.backend = backend
        self.project = project
        self.limit = limit
        self.jql_extra = jql_extra
        self.scope_label = project

    def list_tasks(
        self,
        query: Optional[str] = None,
        refresh: bool = False,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        updated_since: Optional[str] = None,
        include_closed: bool = False,
    ) -> Sequence[TaskSummary]:
        if query:
            return self.backend.search_tasks(
                self.project,
                query,
                limit=self.limit,
                jql_extra=self.jql_extra,
                assignee_filter=assignee_filter,
                updated_since=updated_since,
                include_done=include_closed,
            )
        return self.backend.list_tasks(
            self.project,
            limit=self.limit,
            jql_extra=self.jql_extra,
            assignee_filter=assignee_filter,
            updated_since=updated_since,
            include_done=include_closed,
        )

    def list_updates(self, scope: str, since: str):
        return self.backend.list_updates(scope, since)

    def list_children(self, parents):
        return self.backend.list_children(parents)

    def get_task(self, identity: BackendIdentity, refresh: bool = False) -> TaskDetail:
        if identity.backend is not Backend.JIRA:
            raise JiraError("Cannot open a non-Jira task with the Jira backend.")
        return self.backend.get_task(identity.key)


class GithubTuiBackend:
    backend_label = "GitHub"

    def __init__(self, backend: GithubBackend, repository: str) -> None:
        self.backend = backend
        self.repository = repository
        self.scope_label = repository

    def list_tasks(
        self,
        query: Optional[str] = None,
        refresh: bool = False,
        assignee_filter: AssigneeFilter = AssigneeFilter.ALL,
        *,
        updated_since: Optional[str] = None,
        include_closed: bool = False,
    ) -> Sequence[TaskSummary]:
        if query:
            return self.backend.search_issues(
                query,
                assignee_filter=assignee_filter,
                updated_since=updated_since,
                include_closed=include_closed,
            )
        return self.backend.list_issues(
            assignee_filter=assignee_filter,
            updated_since=updated_since,
            include_closed=include_closed,
        )

    def list_updates(self, scope: str, since: str):
        return self.backend.list_updates(scope, since)

    def get_task(self, identity: BackendIdentity, refresh: bool = False) -> TaskDetail:
        if identity.backend is not Backend.GITHUB:
            raise GithubError("Cannot open a non-GitHub task with the GitHub backend.")
        return self.backend.get_issue(identity)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasks",
        description="Browse Jira or GitHub issues in a read-only terminal UI; omit backend flags to choose interactively.",
    )
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--jira", action="store_true", help="use Jira through acli")
    backend.add_argument("--gh", action="store_true", help="use GitHub Issues through gh")
    parser.add_argument("target", nargs="?", help="issue key, number, qualified reference, or URL")
    parser.add_argument("--project", type=_project, help="Jira project key")
    parser.add_argument(
        "--repo", type=_repository, help="GitHub repository in owner/repo form (issues and/or PRs)"
    )
    parser.add_argument("--query", help="start with a backend search")
    parser.add_argument("--limit", type=_limit, help="maximum issues to load (1-1000)")
    parser.add_argument("--config", help="YAML config path")
    parser.add_argument("--jql-extra", help="additional Jira JQL clause")
    parser.add_argument("--search", help="additional GitHub issue search qualifiers (with --gh)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.target and args.query:
            parser.error("--query cannot be used with a direct issue target")
        if not args.jira and not args.gh:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                parser.error("pass --gh or --jira when running without an interactive terminal")
            from .tui.launcher import pick_backend

            target = jira_identity(args.target) if args.target else None
            selected = pick_backend(
                load_recent_backend(),
                needs_project=not (args.project or config.jira.default_project or target),
                validate_project=_project,
            )
            if selected is None:
                return 0
            args.jira = selected.backend is Backend.JIRA
            args.gh = selected.backend is Backend.GITHUB
            if selected.project is not None:
                args.project = selected.project
        if args.jira:
            _run_jira(parser, args, config)
        else:
            _run_github(parser, args, config)
    except (ConfigError, JiraError, GithubError, ValueError) as error:
        print(f"tasks: {error}", file=sys.stderr)
        return 2
    return 0


def _run_jira(
    parser: argparse.ArgumentParser, args: argparse.Namespace, config: TasksConfig
) -> None:
    if args.search:
        parser.error("--search is only valid with --gh")

    identity = jira_identity(args.target) if args.target else None
    if args.target and identity is None:
        parser.error("Jira target must be an issue key or /browse/KEY URL")
    project = args.project or config.jira.default_project
    if identity:
        target_project = identity.key.rsplit("-", 1)[0]
        if args.project and args.project != target_project:
            parser.error("--project does not match the direct Jira issue")
        project = target_project
    if not project:
        parser.error("Jira list mode requires --project KEY or jira.default_project in config")

    backend = JiraBackend(config.jira)
    try:
        backend.validate()
    except JiraError:
        if not _has_saved_issues(f"jira:{project.upper()}"):
            raise
    adapter = JiraTuiBackend(
        backend,
        project.upper(),
        limit=args.limit,
        jql_extra=args.jql_extra,
    )
    pulls, pulls_error = _make_pulls_backend(
        explicit=args.repo,
        config_default=config.github.default_repo,
        limit=args.limit or config.github.limit,
    )
    excludes = _pull_excludes_for(config, pulls.repository if pulls else "")
    _run_tui(
        adapter,
        f"jira:{project.upper()}",
        identity,
        args.query,
        pulls_backend=pulls,
        pulls_error=pulls_error,
        pull_excludes=excludes,
    )


def _run_github(
    parser: argparse.ArgumentParser, args: argparse.Namespace, config: TasksConfig
) -> None:
    if args.project or args.jql_extra:
        parser.error("--project and --jql-extra are only valid with --jira")

    configured_repo = args.repo or config.github.default_repo
    identity = github_identity(args.target) if args.target else None
    if args.target and identity is None and not re.fullmatch(r"#?\d+", args.target.strip()):
        parser.error("GitHub target must be a number, owner/repo#number, or issue URL")
    if args.target and identity and args.repo:
        if identity.repository != args.repo.lower():
            parser.error("--repo does not match the direct GitHub issue")
    repository = identity.repository if identity else configured_repo
    backend = GithubBackend(
        repository,
        limit=args.limit or config.github.limit,
        search=args.search if args.search is not None else config.github.search,
    )
    try:
        repository = backend.validate()
    except GithubError:
        repository = repository or _local_github_repository()
        if not repository or not _has_saved_issues(f"github:{repository.lower()}"):
            raise
        backend.repository = repository
    if args.target and identity is None:
        identity = github_identity(args.target, default_repo=repository)
        if identity is None:
            parser.error("GitHub target must be a number, owner/repo#number, or issue URL")
    adapter = GithubTuiBackend(backend, repository)
    pulls, pulls_error = _make_pulls_backend(
        explicit=repository,
        config_default=None,
        limit=args.limit or config.github.limit,
    )
    excludes = _pull_excludes_for(config, repository)
    _run_tui(
        adapter,
        f"github:{repository.lower()}",
        identity,
        args.query,
        pulls_backend=pulls,
        pulls_error=pulls_error,
        pull_excludes=excludes,
    )


def _local_github_repository() -> Optional[str]:
    """Resolve an offline cache scope from this checkout's origin."""
    from .process import ProcessError, run_text

    try:
        remote = run_text(["git", "remote", "get-url", "origin"], timeout=5).strip()
    except ProcessError:
        return None
    match = re.fullmatch(
        r"(?:git@github\.com:|ssh://git@github\.com/|https?://github\.com/)"
        r"([^/\s]+/[^/\s]+?)(?:\.git)?/?",
        remote,
    )
    return match[1].lower() if match else None


def _has_saved_issues(scope: str) -> bool:
    from .cache import CacheError
    from .issue_cache import load_store

    try:
        return bool(load_store(scope).items)
    except CacheError:
        return False


def _make_pulls_backend(
    *,
    explicit: Optional[str],
    config_default: Optional[str],
    limit: int,
) -> tuple[Optional[GithubPullsBackend], Optional[str]]:
    repository = resolve_github_repository(
        explicit=explicit,
        config_default=config_default,
    )
    if repository is None:
        return None, (
            "No GitHub repository for pull requests. "
            "Pass --repo owner/repo, set github.default_repo, or run inside a GitHub checkout."
        )
    try:
        return GithubPullsBackend(repository, limit=limit), None
    except (ValueError, GithubError) as error:
        return None, str(error)


def _pull_excludes_for(config: TasksConfig, repository: str) -> tuple[str, ...]:
    if not repository:
        return ()
    mapping = getattr(config.github, "pull_excludes", None)
    if not isinstance(mapping, dict):
        return ()
    patterns = mapping.get(repository.lower(), ())
    if not isinstance(patterns, (list, tuple)):
        return ()
    return tuple(item for item in patterns if isinstance(item, str) and item.strip())


def _run_tui(
    adapter: "TaskBackend",
    scope: str,
    identity: Optional[BackendIdentity],
    query: Optional[str],
    *,
    pulls_backend: Optional[GithubPullsBackend] = None,
    pulls_error: Optional[str] = None,
    pull_excludes: Sequence[str] = (),
) -> None:
    from .tui import run

    loaded = load_assignee_filter(scope)
    if loaded.warning:
        print(f"tasks: warning: {loaded.warning}", file=sys.stderr)

    loaded_work = load_work_filter(scope)

    def persist_work(selection: WorkFilter) -> None:
        if selection is WorkFilter.ALL:
            clear_work_filter(scope)
        else:
            save_work_filter(scope, selection)

    def persist(selection: AssigneeFilter) -> None:
        if selection is AssigneeFilter.ALL:
            clear_assignee_filter(scope)
        else:
            save_assignee_filter(scope, selection)

    try:
        save_recent_backend(Backend(scope.split(":", 1)[0]))
    except OSError as error:
        print(f"tasks: warning: could not remember backend: {error}", file=sys.stderr)

    run(
        adapter,
        initial_identity=identity,
        query=query,
        initial_assignee_filter=loaded.selection,
        initial_work_filter=loaded_work.selection,
        on_work_filter_change=persist_work,
        on_assignee_filter_change=persist,
        cache_scope=scope,
        pulls_backend=pulls_backend,
        pulls_error=pulls_error,
        pull_excludes=pull_excludes,
    )


def _limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 1000") from error
    if not 1 <= limit <= 1000:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 1000")
    return limit


def _project(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise argparse.ArgumentTypeError("project must be a valid Jira project key")
    return value.upper()


def _repository(value: str) -> str:
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        raise argparse.ArgumentTypeError("repo must use owner/repository format")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
