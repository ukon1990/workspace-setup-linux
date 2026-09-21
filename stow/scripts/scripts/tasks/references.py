"""Extract backend task references from descriptions and comments."""

import re
from typing import Iterable, Optional, Tuple

from .models import BackendIdentity, TaskReference

_JIRA_URL_RE = re.compile(
    r"https?://[A-Za-z0-9.-]+(?::\d+)?/browse/([A-Za-z][A-Za-z0-9_]*-\d+)",
    re.IGNORECASE,
)
_JIRA_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]*-\d+)\b")
_GITHUB_ISSUE_URL_RE = re.compile(
    r"https?://github\.com/([^/\s]+)/([^/\s]+)/issues/(\d+)\b",
    re.IGNORECASE,
)
_GITHUB_REFERENCE_URL_RE = re.compile(
    r"https?://github\.com/([^/\s]+)/([^/\s]+)/(?:issues|pull)/(\d+)\b",
    re.IGNORECASE,
)
_GITHUB_QUALIFIED_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#(\d+)\b")
_GITHUB_NUMBER_RE = re.compile(r"(?<![\w/])#(\d+)\b")


def parse_jira_references(
    text: str, *, current: Optional[BackendIdentity] = None
) -> Tuple[TaskReference, ...]:
    references = []
    for match in _JIRA_URL_RE.finditer(text or ""):
        references.append(
            TaskReference(
                BackendIdentity.jira(match.group(1), url=match.group(0)),
                match.group(0),
            )
        )
    for match in _JIRA_KEY_RE.finditer(text or ""):
        references.append(TaskReference(BackendIdentity.jira(match.group(1)), match.group(0)))
    return _deduplicate(references, current)


def parse_github_references(
    text: str,
    *,
    default_repo: Optional[str] = None,
    current: Optional[BackendIdentity] = None,
) -> Tuple[TaskReference, ...]:
    references = []
    occupied = []
    for match in _GITHUB_REFERENCE_URL_RE.finditer(text or ""):
        repo = f"{match.group(1)}/{match.group(2)}"
        references.append(
            TaskReference(
                BackendIdentity.github(int(match.group(3)), repo, url=match.group(0)),
                match.group(0),
            )
        )
        occupied.append(match.span())
    for match in _GITHUB_QUALIFIED_RE.finditer(text or ""):
        if _overlaps(match.span(), occupied):
            continue
        repo = f"{match.group(1)}/{match.group(2)}"
        references.append(
            TaskReference(
                BackendIdentity.github(int(match.group(3)), repo),
                match.group(0),
            )
        )
        occupied.append(match.span())
    if default_repo:
        for match in _GITHUB_NUMBER_RE.finditer(text or ""):
            if not _overlaps(match.span(), occupied):
                references.append(
                    TaskReference(
                        BackendIdentity.github(int(match.group(1)), default_repo),
                        match.group(0),
                    )
                )
    return _deduplicate(references, current)


def jira_identity(value: str) -> Optional[BackendIdentity]:
    url_match = _JIRA_URL_RE.fullmatch(value.strip())
    if url_match:
        return BackendIdentity.jira(url_match.group(1), url=value.strip())
    key_match = _JIRA_KEY_RE.fullmatch(value.strip())
    if key_match:
        return BackendIdentity.jira(key_match.group(1))
    return None


def github_identity(value: str, *, default_repo: Optional[str] = None) -> Optional[BackendIdentity]:
    stripped = value.strip()
    url_match = _GITHUB_ISSUE_URL_RE.fullmatch(stripped)
    if url_match:
        repo = f"{url_match.group(1)}/{url_match.group(2)}"
        return BackendIdentity.github(int(url_match.group(3)), repo, url=stripped)
    qualified_match = _GITHUB_QUALIFIED_RE.fullmatch(stripped)
    if qualified_match:
        repo = f"{qualified_match.group(1)}/{qualified_match.group(2)}"
        return BackendIdentity.github(int(qualified_match.group(3)), repo)
    number_match = re.fullmatch(r"#?(\d+)", stripped)
    if number_match and default_repo:
        return BackendIdentity.github(int(number_match.group(1)), default_repo)
    return None


def _deduplicate(
    references: Iterable[TaskReference], current: Optional[BackendIdentity]
) -> Tuple[TaskReference, ...]:
    seen = {current.stable_id} if current else set()
    result = []
    for reference in references:
        stable_id = reference.target.stable_id
        if stable_id not in seen:
            seen.add(stable_id)
            result.append(reference)
    return tuple(result)


def _overlaps(span: Tuple[int, int], occupied: Iterable[Tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in occupied)
