"""Data model shared by the core pipeline and the UI. Structures only, no logic.

All character offsets are half-open ranges [start, end) into ``SourceDocument.text``.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    """Half-open character range [start, end) in ``SourceDocument.text``."""

    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A non-empty line of the document without surrounding whitespace."""

    index: int
    start: int
    end: int
    text: str
    clause: str | None  # clause number at the line start, e.g. "2.1"
    sentences: tuple[Span, ...]  # sentences of the paragraph body (after the clause number)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A decoded uploaded file. Identity is the content hash, never the filename."""

    doc_id: str
    filename: str  # used for display only
    text: str  # NFC-normalized, LF line endings, no BOM
    encoding: str
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True, slots=True)
class ReadFailure:
    """An uploaded file that could not be read as a text document."""

    filename: str
    reason: str  # user-facing message
