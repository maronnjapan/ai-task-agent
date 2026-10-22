"""Artifact exporters (SPEC 2.4: Markdown first, extensible to other formats)."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ExportResult:
    content: bytes
    extension: str
    media_type: str


Exporter = Callable[[str, str], ExportResult]


def export_markdown(title: str, content: str) -> ExportResult:
    return ExportResult(content.encode("utf-8"), ".md", "text/markdown; charset=utf-8")


def export_text(title: str, content: str) -> ExportResult:
    text = re.sub(r"^#{1,6}\s*", "", content, flags=re.MULTILINE)
    text = re.sub(r"[*_`]{1,3}([^*_`]+)[*_`]{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return ExportResult(text.encode("utf-8"), ".txt", "text/plain; charset=utf-8")


def export_html(title: str, content: str) -> ExportResult:
    """Dependency-free minimal HTML export (headings, paragraphs, lists, code, links)."""
    lines = content.splitlines()
    out: list[str] = []
    in_code = False
    in_list = False
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in lines:
        if line.strip().startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                out.append("</code></pre>")
            else:
                out.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        item = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if item:
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(item.group(1))}</li>")
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        paragraph.append(line.strip())
    flush_paragraph()
    close_list()
    if in_code:
        out.append("</code></pre>")
    body = "\n".join(out)
    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:sans-serif;max-width:48rem;margin:2rem auto;padding:0 1rem;line-height:1.6}"
        "pre{background:#f4f4f4;padding:.75rem;overflow:auto}code{font-family:monospace}</style>"
        f"</head><body>{body}</body></html>"
    )
    return ExportResult(document.encode("utf-8"), ".html", "text/html; charset=utf-8")


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


EXPORTERS: dict[str, Exporter] = {
    "markdown": export_markdown,
    "md": export_markdown,
    "text": export_text,
    "txt": export_text,
    "html": export_html,
}


def register_exporter(name: str, exporter: Exporter) -> None:
    EXPORTERS[name.lower()] = exporter


def export(fmt: str, title: str, content: str) -> ExportResult:
    exporter = EXPORTERS.get(fmt.lower())
    if exporter is None:
        raise KeyError(f"Unsupported export format: {fmt}. Available: {sorted(set(EXPORTERS))}")
    return exporter(title, content)
