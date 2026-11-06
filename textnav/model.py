"""Data model shared by the core pipeline and the UI. Structures only, no logic.

All character offsets are half-open ranges [start, end) into ``SourceDocument.text``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any


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


class DocType(StrEnum):
    CONTRACT = "contract"
    AMENDMENT = "amendment"
    AMENDMENT_DRAFT = "amendment_draft"
    LETTER = "letter"
    UNKNOWN = "unknown"


class SignatureStatus(StrEnum):
    SIGNED_BOTH = "signed_both"
    SIGNED_PARTIAL = "signed_partial"
    NOT_SIGNED = "not_signed"
    UNKNOWN = "unknown"


class ExtractionState(StrEnum):
    FOUND = "found"  # exactly one distinct value
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"  # several distinct values
    STATED_ABSENT = "stated_absent"  # the text explicitly says the value is not specified
    UNPARSED = "unparsed"  # the field is mentioned in a change, but its value is not recognized


@dataclass(frozen=True, slots=True)
class Citation:
    """Exact evidence: ``quote == text[start:end]`` (a sentence) with an optional value span."""

    doc_id: str
    filename: str
    paragraph: int
    start: int
    end: int
    quote: str
    value_start: int | None = None
    value_end: int | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    """Result of extracting one field from one document."""

    field: str
    state: ExtractionState
    value: Any = None  # set only for FOUND
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Signature:
    status: SignatureStatus
    date: date | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Document-level facts used for linking and for the applicability rules."""

    doc_type: DocType
    number: Extraction  # own number: contract number for a contract, "1" for amendment No. 1
    contract_number: Extraction  # normalized number of the contract the document belongs to
    supplier: Extraction
    doc_date: Extraction
    signature: Signature
    effective_date: Extraction


@dataclass(frozen=True, slots=True)
class ChangeClause:
    """A paragraph of a change document that intends to change the contract."""

    citation: Citation
    target_clause: str | None  # contract clause it rewrites, e.g. "2.1" in "Пункт 2.1 ... изложить"
    fields: tuple[str, ...]  # registry fields touched: value found or mentioned without one


@dataclass(frozen=True, slots=True)
class DocumentAnalysis:
    source: SourceDocument
    meta: DocumentMeta
    terms: dict[str, Extraction]  # keyed by FieldSpec.name, in registry order
    change_clauses: tuple[ChangeClause, ...]
