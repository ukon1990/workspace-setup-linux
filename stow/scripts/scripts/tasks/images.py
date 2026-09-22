"""Download and split Markdown images for terminal rendering."""

from __future__ import annotations

import hashlib
import os
import re
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .process import ProcessError, run_text

DEFAULT_IMAGE_CACHE_DIR = Path("~/.local/state/tasks/image-cache")
_MAX_BYTES = 12 * 1024 * 1024
_TIMEOUT = 20
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SKIP_SCHEMES = frozenset({"media", "data", "about"})
_GITHUB_HOST_HINTS = ("github.com", "githubusercontent.com", "github.io")
_JIRA_HOST_HINTS = ("atlassian.net", "atlassian.com", "jira")

_gh_token: Optional[str] = None
_gh_token_checked = False


@dataclass(frozen=True)
class ContentSegment:
    """One slice of a Markdown body: plain text or an image reference."""

    kind: str  # "text" | "image"
    text: str = ""
    alt: str = ""
    url: str = ""


def split_markdown_images(markdown: str) -> Tuple[ContentSegment, ...]:
    """Split Markdown into text and image segments (inline `![alt](url)` only)."""
    if not markdown:
        return (ContentSegment("text", text=""),)
    segments: list[ContentSegment] = []
    cursor = 0
    for match in _IMAGE_RE.finditer(markdown):
        if match.start() > cursor:
            segments.append(ContentSegment("text", text=markdown[cursor : match.start()]))
        url = match.group(2).strip()
        if _is_fetchable_image_url(url):
            segments.append(
                ContentSegment("image", alt=match.group(1).strip(), url=url)
            )
        else:
            segments.append(ContentSegment("text", text=match.group(0)))
        cursor = match.end()
    if cursor < len(markdown):
        segments.append(ContentSegment("text", text=markdown[cursor:]))
    return tuple(segments) if segments else (ContentSegment("text", text=markdown),)


def markdown_image_urls(markdown: str) -> Tuple[str, ...]:
    """Unique fetchable image URLs in document order."""
    seen: set[str] = set()
    urls: list[str] = []
    for segment in split_markdown_images(markdown):
        if segment.kind != "image" or segment.url in seen:
            continue
        seen.add(segment.url)
        urls.append(segment.url)
    return tuple(urls)


def fetch_images(
    urls: Sequence[str],
    *,
    cache_dir: Optional[Path] = None,
) -> dict[str, Path]:
    """Download image URLs into a local cache. Failed URLs are omitted."""
    root = (cache_dir or DEFAULT_IMAGE_CACHE_DIR).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, Path] = {}
    for url in urls:
        path = fetch_image(url, cache_dir=root)
        if path is not None:
            resolved[url] = path
    return resolved


def fetch_image(url: str, *, cache_dir: Optional[Path] = None) -> Optional[Path]:
    """Fetch one image URL to the cache. Returns None on failure."""
    if not _is_fetchable_image_url(url):
        return None
    root = (cache_dir or DEFAULT_IMAGE_CACHE_DIR).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = root / _cache_name(url)
    if path.is_file() and path.stat().st_size > 0:
        return path
    try:
        data = _download_bytes(url)
    except (OSError, URLError, HTTPError, TimeoutError, ValueError):
        return None
    if not data:
        return None
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return path


def _is_fetchable_image_url(url: str) -> bool:
    if not url or url.startswith("#"):
        return False
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").casefold()
    if scheme in _SKIP_SCHEMES:
        return False
    if scheme in {"http", "https"}:
        return bool(parsed.netloc)
    return False


def _cache_name(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    suffix = _guess_suffix(url)
    return f"{digest}{suffix}"


def _guess_suffix(url: str) -> str:
    path = urlparse(url).path.casefold()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".img"


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers=_request_headers(url))
    with urlopen(request, timeout=_TIMEOUT) as response:
        chunk = response.read(_MAX_BYTES + 1)
    if len(chunk) > _MAX_BYTES:
        raise ValueError("image exceeds size limit")
    return chunk


def _request_headers(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": "tasks-tui/1.0",
        "Accept": "image/*,*/*;q=0.8",
    }
    host = urlparse(url).netloc.casefold()
    if any(hint in host for hint in _GITHUB_HOST_HINTS):
        token = _github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif any(hint in host for hint in _JIRA_HOST_HINTS):
        auth = _jira_basic_auth()
        if auth:
            headers["Authorization"] = f"Basic {auth}"
    return headers


def _github_token() -> Optional[str]:
    global _gh_token, _gh_token_checked
    env = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip() or None
    if _gh_token_checked:
        return _gh_token
    _gh_token_checked = True
    try:
        token = run_text(["gh", "auth", "token"], timeout=5).strip()
    except (ProcessError, OSError):
        token = ""
    _gh_token = token or None
    return _gh_token


def _jira_basic_auth() -> Optional[str]:
    email = (
        os.environ.get("JIRA_EMAIL")
        or os.environ.get("ATLASSIAN_EMAIL")
        or ""
    ).strip()
    token = (
        os.environ.get("JIRA_API_TOKEN")
        or os.environ.get("ATLASSIAN_API_TOKEN")
        or ""
    ).strip()
    if not email or not token:
        return None
    raw = f"{email}:{token}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
