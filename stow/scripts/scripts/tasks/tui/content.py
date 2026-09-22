"""Helpers to mount Markdown bodies with inline terminal images."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

from textual.containers import Vertical
from textual.widgets import Markdown

from ..images import ContentSegment, split_markdown_images

try:
    from textual_image.widget import Image as TerminalImage
except ImportError:  # pragma: no cover - optional until setup installs deps
    TerminalImage = None  # type: ignore[misc, assignment]


def populate_content_stack(
    stack: Vertical,
    markdown: str,
    images: Optional[Mapping[str, Path]] = None,
) -> None:
    """Replace stack children with Markdown + Image widgets for *markdown*."""
    images = images or {}
    stack.remove_children()
    segments = split_markdown_images(markdown)
    if TerminalImage is None or not any(seg.kind == "image" for seg in segments):
        stack.mount(Markdown(markdown or "", classes="content-md"))
        return

    pending: list = []
    for index, segment in enumerate(segments):
        widget = _segment_widget(segment, images, index)
        if widget is not None:
            pending.append(widget)
    if not pending:
        stack.mount(Markdown(markdown or "", classes="content-md"))
        return
    stack.mount(*pending)


def _segment_widget(
    segment: ContentSegment,
    images: Mapping[str, Path],
    index: int,
):
    if segment.kind == "text":
        if not segment.text.strip():
            return None
        return Markdown(segment.text, classes="content-md", id=f"content-md-{index}")
    path = images.get(segment.url)
    caption = segment.alt or "image"
    if path is not None and TerminalImage is not None:
        try:
            return TerminalImage(
                str(path),
                classes="detail-image",
                id=f"content-img-{index}",
                on_error=lambda _exc, cap=caption, url=segment.url: Markdown(
                    f"[🖼 {cap}]({url})",
                    classes="content-md",
                ),
            )
        except TypeError:
            # Older textual-image builds omit on_error.
            return TerminalImage(
                str(path),
                classes="detail-image",
                id=f"content-img-{index}",
            )
    return Markdown(
        f"[🖼 {caption}]({segment.url})",
        classes="content-md",
        id=f"content-img-fallback-{index}",
    )
