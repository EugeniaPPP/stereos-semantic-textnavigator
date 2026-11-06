"""Citations and aggregation of value candidates, shared by metadata and term extraction."""

from collections.abc import Iterable, Iterator
from typing import Any

from textnav.model import Citation, Extraction, ExtractionState, Paragraph, SourceDocument, Span


def cite(
    doc: SourceDocument,
    paragraph: Paragraph,
    span: Span,
    value_start: int | None = None,
    value_end: int | None = None,
) -> Citation:
    """Citation of ``span`` (absolute offsets) with an optional highlighted value inside it."""
    return Citation(
        doc_id=doc.doc_id,
        filename=doc.filename,
        paragraph=paragraph.index,
        start=span.start,
        end=span.end,
        quote=doc.text[span.start : span.end],
        value_start=value_start,
        value_end=value_end,
    )


def iter_sentences(doc: SourceDocument) -> Iterator[tuple[Paragraph, Span, str]]:
    for paragraph in doc.paragraphs:
        for span in paragraph.sentences:
            yield paragraph, span, doc.text[span.start : span.end]


def collect(field: str, candidates: Iterable[tuple[Any, Citation]]) -> Extraction:
    """FOUND for exactly one distinct value, AMBIGUOUS for several, NOT_FOUND for none."""
    values: list[Any] = []
    citations: list[Citation] = []
    for value, citation in candidates:
        if value not in values:
            values.append(value)
        if citation not in citations:
            citations.append(citation)
    if not values:
        return Extraction(field, ExtractionState.NOT_FOUND)
    if len(values) > 1:
        return Extraction(field, ExtractionState.AMBIGUOUS, citations=tuple(citations))
    return Extraction(field, ExtractionState.FOUND, values[0], tuple(citations))
