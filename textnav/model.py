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


# --- resolution ---------------------------------------------------------------


class ChangeStatus(StrEnum):
    APPLIED = "applied"  # signed by both parties and in force on the check date
    NOT_YET_EFFECTIVE = "not_yet_effective"  # signed by both, but signed or effective later
    PROPOSAL = "proposal"  # not agreed: letter, unsigned draft, signed by one party
    NEEDS_REVIEW = "needs_review"  # status or dates unreliable, or type contradicts status


class ContractStatus(StrEnum):
    IN_FORCE = "in_force"
    NOT_IN_FORCE = "not_in_force"
    NEEDS_REVIEW = "needs_review"


class ValueState(StrEnum):
    VALUE = "value"
    NO_DATA = "no_data"
    NEEDS_REVIEW = "needs_review"
    NOT_IN_FORCE = "not_in_force"  # the contract itself is not in force on the check date


class AlertCode(StrEnum):
    CONTRACT_NOT_IN_FORCE = "contract_not_in_force"
    CONTRACT_NEEDS_REVIEW = "contract_needs_review"
    CHANGE_PENDING = "change_pending"  # signed, not yet effective
    CHANGE_PROPOSAL = "change_proposal"  # not agreed
    CHANGE_NEEDS_REVIEW = "change_needs_review"
    FIELD_NEEDS_REVIEW = "field_needs_review"
    UNRECOGNIZED_CHANGE = "unrecognized_change"
    EMPTY_AMENDMENT = "empty_amendment"
    SUPPLIER_MISMATCH = "supplier_mismatch"


class AttentionReason(StrEnum):
    ORPHAN = "orphan"  # processed, but its contract is not uploaded
    UNLINKED = "unlinked"
    UNKNOWN_TYPE = "unknown_type"
    READ_ERROR = "read_error"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ContractGroup:
    number: str
    contracts: tuple[DocumentAnalysis, ...]  # base contract documents, normally exactly one
    changes: tuple[DocumentAnalysis, ...]  # amendments, drafts, letters


@dataclass(frozen=True, slots=True)
class ChangeDoc:
    analysis: DocumentAnalysis
    status: ChangeStatus
    reason: str
    changes: dict[str, Extraction]  # fields this document touches


@dataclass(frozen=True, slots=True)
class TermValue:
    state: ValueState
    value: Any = None
    citations: tuple[Citation, ...] = ()
    source_doc_id: str | None = None  # document that established the value
    reason: str = ""  # why NO_DATA / NEEDS_REVIEW


@dataclass(frozen=True, slots=True)
class TermResolution:
    field: str
    label: str
    original: TermValue  # from the contract
    applied: TermValue  # after applied amendments: the last confirmed value
    effective: (
        TermValue  # shown on the check date (NEEDS_REVIEW if an unreliable change touches it)
    )
    changed_by: tuple[str, ...]  # doc ids of applied amendments that touched the field


@dataclass(frozen=True, slots=True)
class Alert:
    code: AlertCode
    message: str
    field: str | None = None
    doc_id: str | None = None
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ContractView:
    number: str
    supplier: Extraction
    status: ContractStatus
    status_reason: str
    contracts: tuple[DocumentAnalysis, ...]
    terms: dict[str, TermResolution]
    change_docs: tuple[ChangeDoc, ...]
    alerts: tuple[Alert, ...]


@dataclass(frozen=True, slots=True)
class AttentionItem:
    reason: AttentionReason
    message: str
    filename: str
    analysis: DocumentAnalysis | None = None
    change: ChangeDoc | None = None  # status of an orphan change document
