"""Offline review draft store for PR inline comments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

DRAFTS_PATH = Path.home() / ".local" / "state" / "tasks" / "review-drafts.yaml"


@dataclass
class DraftComment:
    path: str
    side: str
    line: int
    body: str
    start_line: Optional[int] = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ReviewDraft:
    stable_id: str
    comments: List[DraftComment] = field(default_factory=list)
    body: str = ""

    def comments_for_path(self, path: str) -> List[DraftComment]:
        return [c for c in self.comments if c.path == path]

    def count_for_path(self, path: str) -> int:
        return sum(1 for c in self.comments if c.path == path)


def load_drafts(path: Path | None = None) -> Dict[str, ReviewDraft]:
    store = path or DRAFTS_PATH
    if not store.exists():
        return {}
    raw = yaml.safe_load(store.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, ReviewDraft] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        comments = [
            DraftComment(
                path=str(item.get("path") or ""),
                side=str(item.get("side") or "RIGHT"),
                line=int(item.get("line") or 0),
                body=str(item.get("body") or ""),
                start_line=item.get("start_line"),
                created_at=str(item.get("created_at") or ""),
            )
            for item in value.get("comments") or []
            if isinstance(item, dict)
        ]
        out[str(key)] = ReviewDraft(
            stable_id=str(key),
            comments=comments,
            body=str(value.get("body") or ""),
        )
    return out


def save_drafts(drafts: Dict[str, ReviewDraft], path: Path | None = None) -> None:
    store = path or DRAFTS_PATH
    store.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {
            "body": draft.body,
            "comments": [asdict(c) for c in draft.comments],
        }
        for key, draft in drafts.items()
        if draft.body or draft.comments
    }
    store.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def get_draft(stable_id: str, path: Path | None = None) -> ReviewDraft:
    drafts = load_drafts(path)
    return drafts.get(stable_id) or ReviewDraft(stable_id=stable_id)


def add_draft_comment(
    stable_id: str,
    comment: DraftComment,
    path: Path | None = None,
) -> ReviewDraft:
    drafts = load_drafts(path)
    draft = drafts.get(stable_id) or ReviewDraft(stable_id=stable_id)
    draft.comments.append(comment)
    drafts[stable_id] = draft
    save_drafts(drafts, path)
    return draft


def set_draft_body(stable_id: str, body: str, path: Path | None = None) -> ReviewDraft:
    drafts = load_drafts(path)
    draft = drafts.get(stable_id) or ReviewDraft(stable_id=stable_id)
    draft.body = body
    drafts[stable_id] = draft
    save_drafts(drafts, path)
    return draft


def clear_draft(stable_id: str, path: Path | None = None) -> None:
    drafts = load_drafts(path)
    if stable_id in drafts:
        del drafts[stable_id]
        save_drafts(drafts, path)
