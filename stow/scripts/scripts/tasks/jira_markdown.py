"""Atlassian Document Format and attachment rendering helpers."""

from typing import Any, Iterable, Mapping, Optional, Sequence

_MEDIA_TYPES = frozenset({"media", "mediaSingle", "mediaGroup", "mediaInline"})
_BLOCK_TYPES = frozenset(
    {
        "doc",
        "blockquote",
        "bulletList",
        "orderedList",
        "panel",
        "expand",
        "layoutSection",
        "layoutColumn",
    }
)


def _attachment_index(value: Any) -> dict[str, str]:
    """Map lowercase filename → content URL for media matching."""
    if not isinstance(value, list):
        return {}
    index: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text_value(item.get("filename") or item.get("name"))
        url = _text_value(item.get("content") or item.get("url") or item.get("self"))
        if name and url:
            index[name.casefold()] = url
    return index


def _adf_text(value: Any, attachments: Optional[Mapping[str, str]] = None) -> str:
    """Backward-compatible alias for ADF → Markdown conversion."""
    return _adf_markdown(value, attachments)


def _adf_markdown(value: Any, attachments: Optional[Mapping[str, str]] = None) -> str:
    """Convert Atlassian Document Format to Markdown for the detail pane."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _join_blocks(_adf_markdown(item, attachments) for item in value)
    if not isinstance(value, dict):
        return str(value)

    node_type = value.get("type")
    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}

    if node_type == "text":
        return _adf_text_node(value)
    if node_type == "hardBreak":
        return "\n"
    if node_type == "rule":
        return "---"
    if node_type in {"mention", "emoji", "status"}:
        return (
            _text_value(attrs.get("text") or attrs.get("displayName") or attrs.get("shortName"))
            or ""
        )
    if node_type in {"inlineCard", "blockCard", "embedCard"}:
        return _text_value(attrs.get("url")) or ""
    if node_type in _MEDIA_TYPES:
        return _adf_media(value, attachments)

    content = value.get("content")
    if not isinstance(content, list):
        return f"[unsupported:{node_type}]" if node_type else ""

    parts = [_adf_markdown(item, attachments) for item in content]
    if node_type == "heading":
        level = attrs.get("level", 1)
        try:
            level = max(1, min(6, int(level)))
        except (TypeError, ValueError):
            level = 1
        return f"{'#' * level} {_join_inline(parts)}".rstrip()
    if node_type == "codeBlock":
        lang = _text_value(attrs.get("language")) or ""
        body = "\n".join(part.rstrip("\n") for part in parts if part is not None)
        return f"```{lang}\n{body.strip(chr(10))}\n```"
    if node_type == "listItem":
        return f"- {_join_inline(parts)}".rstrip()
    if node_type == "blockquote":
        inner = _join_blocks(parts)
        return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
    if node_type == "panel":
        title = _text_value(attrs.get("panelType")) or "panel"
        inner = _join_blocks(parts)
        return _join_blocks([f"**[{title}]**", inner]) if inner else f"**[{title}]**"
    if node_type == "expand":
        title = _text_value(attrs.get("title")) or "expand"
        inner = _join_blocks(parts)
        return _join_blocks([f"**{title}**", inner]) if inner else f"**{title}**"
    if node_type == "table":
        return _adf_table(parts) if parts else ""
    if node_type == "tableRow":
        cells = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(cells)
    if node_type in {"tableHeader", "tableCell"}:
        return _join_inline(parts)
    if node_type in _BLOCK_TYPES:
        return _join_blocks(parts)
    if node_type == "paragraph":
        return _join_inline(parts)
    rendered = (
        _join_blocks(parts) if parts and any("\n" in p for p in parts if p) else _join_inline(parts)
    )
    return rendered or f"[unsupported:{node_type}]"


def _adf_text_node(value: Mapping[str, Any]) -> str:
    text = _text_value(value.get("text")) or ""
    if not text:
        return ""
    marks = value.get("marks") if isinstance(value.get("marks"), list) else []
    link = None
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mark_type = mark.get("type")
        mark_attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
        if mark_type == "link":
            link = _text_value(mark_attrs.get("href"))
        elif mark_type == "strong":
            text = f"**{text}**"
        elif mark_type == "em":
            text = f"*{text}*"
        elif mark_type == "code":
            text = f"`{text}`"
        elif mark_type in {"strike", "strikethrough"}:
            text = f"~~{text}~~"
    if link and link not in text:
        return f"[{text}]({link})"
    return text


def _adf_media(value: Mapping[str, Any], attachments: Optional[Mapping[str, str]]) -> str:
    """Render media containers/leaves as Markdown image or placeholder links."""
    node_type = value.get("type")
    content = value.get("content")
    if node_type in {"mediaSingle", "mediaGroup"} and isinstance(content, list):
        return _join_blocks(
            _adf_media(item, attachments) for item in content if isinstance(item, dict)
        )

    attrs = value.get("attrs") if isinstance(value.get("attrs"), dict) else {}
    alt = (
        _text_value(attrs.get("alt"))
        or _text_value(attrs.get("name"))
        or _text_value(attrs.get("id"))
        or "image"
    )
    url = _text_value(attrs.get("url"))
    if not url and attachments:
        url = attachments.get(alt.casefold())
    if url:
        return f"![{alt}]({url})"
    media_id = _text_value(attrs.get("id"))
    label = alt if alt != media_id else (media_id or "image")
    target = f"media:{media_id}" if media_id else label
    return f"[🖼 {label}]({target})"


def _adf_table(row_parts: Sequence[str]) -> str:
    rows = [part.strip() for part in row_parts if part and part.strip()]
    if not rows:
        return ""
    # tableRow children arrive as joined cell text; split was already inline-joined.
    # Prefer keeping each row as a single line of cell text separated earlier.
    formatted = []
    for index, row in enumerate(rows):
        cells = [cell.strip() for cell in row.split(" | ")] if " | " in row else [row]
        formatted.append("| " + " | ".join(cells) + " |")
        if index == 0:
            formatted.append("| " + " | ".join("---" for _ in cells) + " |")
    return "\n".join(formatted)


def _join_inline(parts: Iterable[str]) -> str:
    output = ""
    for part in parts:
        if not part:
            continue
        if (
            output
            and not output.endswith(("\n", " "))
            and not part.startswith(("\n", " ", ".", ","))
        ):
            output += " "
        output += part
    return output.strip()


def _join_blocks(parts: Iterable[str]) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _text_value(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None
