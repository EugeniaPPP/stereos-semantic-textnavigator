"""Source document viewer: the whole document with the cited paragraph, quote and value marked.

Uploaded text is untrusted: every fragment of it is HTML-escaped, so it can never add markup
or scripts. The only script in the page is ours: it scrolls to the cited paragraph.
"""

import html

import streamlit as st

from textnav.model import Citation, SourceDocument

_STYLE = """
body { margin: 0; padding: 12px 14px; color: #1B2430; background: #FFFFFF;
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
p { margin: 0 0 0.55em; }
p.target { background: #EEF2F6; border-left: 3px solid #1D4E89; padding: 0.35em 0.6em; }
.quote { background: rgba(29, 78, 137, 0.10); }
mark { background: #FFE08A; color: inherit; padding: 0 0.1em; }
"""

_SCROLL = '<script>document.getElementById("target").scrollIntoView({block: "center"});</script>'


def document_html(doc: SourceDocument, citation: Citation) -> str:
    """Full HTML page of the document; the cited paragraph has ``id="target"``."""
    paragraphs = []
    for paragraph in doc.paragraphs:
        if paragraph.index == citation.paragraph:
            body = _marked(doc.text, paragraph.start, paragraph.end, citation)
            paragraphs.append(f'<p id="target" class="target">{body}</p>')
        else:
            text = _escape(doc.text[paragraph.start : paragraph.end])
            paragraphs.append(f'<p id="p{paragraph.index}">{text}</p>')
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<style>{_STYLE}</style></head><body>{''.join(paragraphs)}{_SCROLL}</body></html>"
    )


def location(doc: SourceDocument, citation: Citation) -> str:
    """Markdown location: "`file.txt`, абзац 6, п. 2.1"."""
    paragraph = doc.paragraphs[citation.paragraph]
    place = f"`{doc.filename.replace('`', '')}`, абзац {paragraph.index + 1}"
    return f"{place}, п. {paragraph.clause}" if paragraph.clause else place


def render_viewer(doc: SourceDocument, citation: Citation) -> None:
    st.caption(f"Источник: {location(doc, citation)}")
    st.iframe(document_html(doc, citation), height=580)


def _marked(text: str, start: int, end: int, citation: Citation) -> str:
    parts = [_escape(text[start : citation.start]), '<span class="quote">']
    if citation.value_start is None:
        parts.append(_escape(text[citation.start : citation.end]))
    else:
        parts += [
            _escape(text[citation.start : citation.value_start]),
            "<mark>",
            _escape(text[citation.value_start : citation.value_end]),
            "</mark>",
            _escape(text[citation.value_end : citation.end]),
        ]
    parts += ["</span>", _escape(text[citation.end : end])]
    return "".join(parts)


def _escape(text: str) -> str:
    return html.escape(text, quote=True)
