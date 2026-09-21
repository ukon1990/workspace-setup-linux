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


class CiState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    SKIPPING = "skipping"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CiCheck:
    name: str
    state: CiState
    bucket: Optional[str] = None
    link: Optional[str] = None


@dataclass(frozen=True)
class ReviewComment:
    """A GitHub pull-request review comment anchored to a diff line."""

    id: int
    path: str
    body: str
    author: str = ""
    side: str = "RIGHT"
    line: Optional[int] = None
    start_line: Optional[int] = None
    original_line: Optional[int] = None
    original_start_line: Optional[int] = None
    diff_hunk: str = ""
    created_at: Optional[str] = None
    url: Optional[str] = None
    in_reply_to_id: Optional[int] = None

    @property
    def anchor_line(self) -> Optional[int]:
        return self.line if self.line is not None else self.original_line

    @property
    def range_start(self) -> Optional[int]:
        if self.start_line is not None:
            return self.start_line
        if self.original_start_line is not None:
            return self.original_start_line
        return self.anchor_line

    @property
    def range_end(self) -> Optional[int]:
        return self.anchor_line

    def covers_line(self, number: int) -> bool:
        start = self.range_start
        end = self.range_end
        if start is None or end is None:
            return False
        low, high = (start, end) if start <= end else (end, start)
        return low <= number <= high


@dataclass(frozen=True)
class PullSummary:
    repository: str
    number: int
    title: str
    status: str
    author: str = ""
    assignees: Tuple[str, ...] = field(default_factory=tuple)
    labels: Tuple[str, ...] = field(default_factory=tuple)
    url: Optional[str] = None
    is_draft: bool = False
    ci_state: CiState = CiState.UNKNOWN
    review_decision: Optional[str] = None

    @property
    def display_key(self) -> str:
        return f"{self.repository}#{self.number}"

    @property
    def stable_id(self) -> str:
        return f"github-pr:{self.repository}:{self.number}"


@dataclass(frozen=True)
class PullDetail:
    summary: PullSummary
    description: str = ""
    comments: Tuple[Comment, ...] = field(default_factory=tuple)
    checks: Tuple[CiCheck, ...] = field(default_factory=tuple)
    diff: str = ""
    review_comments: Tuple[ReviewComment, ...] = field(default_factory=tuple)

    @property
    def stable_id(self) -> str:
        return self.summary.stable_id
