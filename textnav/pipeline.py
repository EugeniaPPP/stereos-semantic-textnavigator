"""Uploaded files + check date -> AnalysisResult, plus queries used by the UI.

The whole result is a pure function of the file contents and the check date: it is recomputed
from scratch on every call, so nothing stale survives a changed file set or date.
"""

from collections.abc import Iterable
from datetime import date

from textnav.analyze import analyze_document
from textnav.ingest import read_documents
from textnav.linking import link
from textnav.model import (
    Alert,
    AlertCode,
    AnalysisResult,
    AttentionItem,
    AttentionReason,
    ContractView,
    DocumentAnalysis,
    ValueState,
)
from textnav.resolve import resolve_groups
from textnav.terms import TERM_REGISTRY, FieldSpec

MSG_ANALYSIS_ERROR = "Внутренняя ошибка при анализе документа: {error}."


def analyze(
    files: Iterable[tuple[str, bytes]],
    check_date: date,
    registry: tuple[FieldSpec, ...] = TERM_REGISTRY,
) -> AnalysisResult:
    documents, failures = read_documents(files)
    attention = [AttentionItem(AttentionReason.READ_ERROR, f.reason, f.filename) for f in failures]

    analyses: list[DocumentAnalysis] = []
    for doc in documents:
        try:
            analyses.append(analyze_document(doc, registry))
        except Exception as error:  # one broken document must not block the others
            message = MSG_ANALYSIS_ERROR.format(error=type(error).__name__)
            attention.append(AttentionItem(AttentionReason.READ_ERROR, message, doc.filename))

    groups, unlinked = link(analyses)
    contracts, orphans = resolve_groups(groups, check_date, registry)
    return AnalysisResult(
        check_date=check_date,
        contracts=tuple(contracts),
        attention=tuple(sorted([*attention, *unlinked, *orphans], key=_attention_order)),
    )


def contracts_with_delivery_before(
    result: AnalysisResult, day: date, field: str = "delivery_date"
) -> tuple[list[ContractView], int]:
    """Contracts whose effective delivery date is strictly earlier than ``day``.

    Also returns how many contracts were left out because they have no reliable date
    (no data, needs review, or the contract is not in force).
    """
    matching, excluded = [], 0
    for view in result.contracts:
        term = view.terms.get(field)
        if term is None or term.effective.state is not ValueState.VALUE:
            excluded += 1
        elif term.effective.value < day:
            matching.append(view)
    return matching, excluded


def unagreed_changes(view: ContractView, field: str | None = None) -> list[Alert]:
    """Not agreed proposals (letters, drafts, one-party signatures), optionally per field."""
    return [
        alert
        for alert in view.alerts
        if alert.code is AlertCode.CHANGE_PROPOSAL and (field is None or alert.field == field)
    ]


def _attention_order(item: AttentionItem) -> tuple[int, str, str]:
    doc_id = item.analysis.source.doc_id if item.analysis else ""
    return (list(AttentionReason).index(item.reason), doc_id, item.filename)
