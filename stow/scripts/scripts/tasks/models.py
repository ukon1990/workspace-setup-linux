"""Backend-neutral task data consumed by adapters and the TUI."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class Backend(str, Enum):
    JIRA = "jira"
    GITHUB = "github"


@dataclass(frozen=True)
class BackendIdentity:
    backend: Backend
    key: str
    repository: Optional[str] = None
    url: Optional[str] = None

    @classmethod
    def jira(cls, key: str, url: Optional[str] = None) -> "BackendIdentity":
        return cls(Backend.JIRA, key.upper(), url=url)

    @classmethod
    def github(cls, number: int, repository: str, url: Optional[str] = None) -> "BackendIdentity":
        return cls(Backend.GITHUB, str(number), repository=repository.lower(), url=url)

    @property
    def stable_id(self) -> str:
        scope = f"{self.repository}:" if self.repository else ""
        return f"{self.backend.value}:{scope}{self.key}"

    @property
    def display_key(self) -> str:
        if self.backend is Backend.GITHUB and self.repository:
            return f"{self.repository}#{self.key}"
        return self.key


@dataclass(frozen=True)
class Comment:
    author: str
    body: str
    created_at: Optional[str] = None
    url: Optional[str] = None


class RelationshipKind(str, Enum):
    PARENT = "parent"
    CHILD = "child"
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    RELATED = "related"
    MENTIONED = "mentioned"


@dataclass(frozen=True)
class TaskReference:
    target: BackendIdentity
    source_text: str = ""


@dataclass(frozen=True)
class TaskRelationship:
    kind: RelationshipKind
    target: BackendIdentity
    label: str
    summary: Optional[str] = None


@dataclass(frozen=True)
class TaskSummary:
    identity: BackendIdentity
    title: str
    status: str
    task_type: Optional[str] = None
    priority: Optional[str] = None
    assignees: Tuple[str, ...] = field(default_factory=tuple)
    labels: Tuple[str, ...] = field(default_factory=tuple)
    components: Tuple[str, ...] = field(default_factory=tuple)
    url: Optional[str] = None
    parent: Optional[BackendIdentity] = None
    blocked_by: Tuple[BackendIdentity, ...] = field(default_factory=tuple)
    blocks: Tuple[BackendIdentity, ...] = field(default_factory=tuple)

    @property
    def display_key(self) -> str:
        return self.identity.display_key


@dataclass(frozen=True)
class TaskDetail:
    summary: TaskSummary
    description: str = ""
    comments: Tuple[Comment, ...] = field(default_factory=tuple)
    relationships: Tuple[TaskRelationship, ...] = field(default_factory=tuple)

    @property
    def identity(self) -> BackendIdentity:
        return self.summary.identity
