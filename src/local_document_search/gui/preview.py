"""Preview pane: file details and a highlighted excerpt for the selected result."""

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QTextBrowser, QWidget

from ..formatting import format_size
from ..search import SearchHit

# Private-use characters mark matches in snippets; they can't collide with document text
# the way literal brackets or HTML tags could.
HIGHLIGHT_START = ""
HIGHLIGHT_END = ""
PREVIEW_SNIPPET_TOKENS = 40

TYPE_LABELS = {".txt": "Text", ".md": "Markdown", ".pdf": "PDF", ".docx": "Word"}

HIGHLIGHT_STYLE = "background-color: #ffe066; color: #000000; font-weight: 600;"


def type_label(path: Path) -> str:
    extension = path.suffix.lower()
    return TYPE_LABELS.get(extension, extension.lstrip(".").upper() or "File")


def highlight_snippet(snippet: str) -> str:
    """Escape ``snippet`` for HTML and turn match markers into highlighted spans."""
    text = " ".join(html.escape(snippet).split())
    return text.replace(HIGHLIGHT_START, f'<span style="{HIGHLIGHT_STYLE}">').replace(
        HIGHLIGHT_END, "</span>"
    )


def render_preview(hit: SearchHit) -> str:
    path = Path(hit.path)
    modified = datetime.fromtimestamp(hit.mtime).strftime("%Y-%m-%d %H:%M")
    details = [
        ("Location", str(path.parent)),
        ("Type", type_label(path)),
        ("Size", format_size(hit.size)),
        ("Modified", modified),
    ]
    rows = "".join(
        f'<tr><td style="padding-right: 12px; color: #808080;">{label}</td>'
        f"<td>{html.escape(value)}</td></tr>"
        for label, value in details
    )
    return (
        f"<h3>{html.escape(path.name)}</h3>"
        f"<table>{rows}</table>"
        f"<h4>Matching excerpt</h4>"
        f"<p>{highlight_snippet(hit.snippet) or '<i>Matched by file name.</i>'}</p>"
    )


class PreviewPane(QTextBrowser):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setPlaceholderText("Select a result to preview it.")

    def show_hit(self, hit: SearchHit | None) -> None:
        if hit is None:
            self.clear()
        else:
            self.setHtml(render_preview(hit))
