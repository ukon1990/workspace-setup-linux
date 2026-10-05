"""Shared models and utilities for the read-only tasks browser."""

from .config import ConfigError, GithubConfig, JiraConfig, TasksConfig, load_config
from .filters import (
    AssigneeFilter,
    FilterLoadResult,
    FilterStateError,
    WorkFilter,
    WorkFilterLoadResult,
    clear_assignee_filter,
    clear_work_filter,
    load_assignee_filter,
    load_work_filter,
    save_assignee_filter,
    save_work_filter,
)
from .models import (
    Backend,
    BackendIdentity,
    Comment,
    RelationshipKind,
    TaskDetail,
    TaskReference,
    TaskRelationship,
    TaskSummary,
)
from .process import ProcessError, ProcessErrorKind, run_json, run_text

__all__ = [
    "Backend",
    "BackendIdentity",
    "AssigneeFilter",
    "WorkFilter",
    "WorkFilterLoadResult",
    "load_work_filter",
    "save_work_filter",
    "clear_work_filter",
    "Comment",
    "ConfigError",
    "FilterLoadResult",
    "FilterStateError",
    "GithubConfig",
    "JiraConfig",
    "ProcessError",
    "ProcessErrorKind",
    "RelationshipKind",
    "TaskDetail",
    "TaskReference",
    "TaskRelationship",
    "TaskSummary",
    "TasksConfig",
    "clear_assignee_filter",
    "load_assignee_filter",
    "load_config",
    "run_json",
    "run_text",
    "save_assignee_filter",
]
