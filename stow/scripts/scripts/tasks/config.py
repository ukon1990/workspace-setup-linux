"""Strict YAML configuration loading for tasks."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

import yaml

DEFAULT_CONFIG_PATH = Path("~/.config/tasks/config.yaml")
_TOP_LEVEL_KEYS = {"jira", "github"}
_JIRA_KEYS = {"default_project", "limit", "jql_extra"}
_GITHUB_KEYS = {"default_repo", "limit", "search", "pull_excludes"}
_PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


class ConfigError(ValueError):
    """Configuration could not be loaded or validated."""


@dataclass(frozen=True)
class JiraConfig:
    default_project: Optional[str] = None
    limit: int = 100
    jql_extra: Optional[str] = None


@dataclass(frozen=True)
class GithubConfig:
    default_repo: Optional[str] = None
    limit: int = 100
    search: Optional[str] = None
    # owner/repo -> glob or path-prefix patterns excluded from PR line totals
    pull_excludes: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class TasksConfig:
    jira: JiraConfig = field(default_factory=JiraConfig)
    github: GithubConfig = field(default_factory=GithubConfig)


def load_config(path: Optional[Union[str, Path]] = None) -> TasksConfig:
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    if not config_path.exists():
        return TasksConfig()
    if not config_path.is_file():
        raise ConfigError(f"Config path is not a file: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as config_file:
            raw = yaml.safe_load(config_file)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigError(f"Could not read config {config_path}: {error}") from error

    if raw is None:
        return TasksConfig()
    root = _mapping(raw, "config")
    _reject_unknown(root, _TOP_LEVEL_KEYS, "config")

    jira_raw = _section(root, "jira")
    github_raw = _section(root, "github")
    _reject_unknown(jira_raw, _JIRA_KEYS, "jira")
    _reject_unknown(github_raw, _GITHUB_KEYS, "github")

    project = _optional_string(jira_raw, "default_project", "jira")
    if project and not _PROJECT_RE.fullmatch(project):
        raise ConfigError("jira.default_project must be a Jira project key")

    repository = _optional_string(github_raw, "default_repo", "github")
    if repository and not _REPOSITORY_RE.fullmatch(repository):
        raise ConfigError("github.default_repo must use owner/repository format")

    return TasksConfig(
        jira=JiraConfig(
            default_project=project.upper() if project else None,
            limit=_limit(jira_raw, "limit", JiraConfig.limit, "jira"),
            jql_extra=_optional_string(jira_raw, "jql_extra", "jira"),
        ),
        github=GithubConfig(
            default_repo=repository,
            limit=_limit(github_raw, "limit", GithubConfig.limit, "github"),
            search=_optional_string(github_raw, "search", "github"),
            pull_excludes=_pull_excludes(github_raw),
        ),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{name} keys must be strings")
    return value


def _section(root: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = root.get(name, {})
    return _mapping(value, name)


def _reject_unknown(section: Mapping[str, Any], allowed: set, name: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"Unknown {name} config key(s): {', '.join(unknown)}")


def _optional_string(section: Mapping[str, Any], key: str, name: str) -> Optional[str]:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name}.{key} must be a non-empty string")
    return value.strip()


def _pull_excludes(section: Mapping[str, Any]) -> Mapping[str, Tuple[str, ...]]:
    raw = section.get("pull_excludes")
    if raw is None:
        return {}
    mapping = _mapping(raw, "github.pull_excludes")
    result: dict[str, Tuple[str, ...]] = {}
    for repo, patterns in mapping.items():
        if not isinstance(repo, str) or not _REPOSITORY_RE.fullmatch(repo.strip()):
            raise ConfigError(
                "github.pull_excludes keys must use owner/repository format"
            )
        if not isinstance(patterns, list) or not patterns:
            raise ConfigError(
                f"github.pull_excludes.{repo.strip()} must be a non-empty list of patterns"
            )
        cleaned: list[str] = []
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ConfigError(
                    f"github.pull_excludes.{repo.strip()} patterns must be non-empty strings"
                )
            cleaned.append(pattern.strip().replace("\\", "/"))
        result[repo.strip().lower()] = tuple(cleaned)
    return result


def _limit(section: Mapping[str, Any], key: str, default: int, name: str) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ConfigError(f"{name}.{key} must be an integer from 1 to 1000")
    return value
