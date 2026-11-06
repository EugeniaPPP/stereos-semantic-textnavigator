"""Contract details: effective values with their basis and quotes, changes grouped by status,
and the source viewer next to them.
"""

import re

import streamlit as st

from textnav.evidence import cite
from textnav.formatting import describe_extraction, document_label, lower_first, value_text
from textnav.model import (
    AlertCode,
    AnalysisResult,
    ChangeStatus,
    Citation,
    ContractStatus,
    ContractView,
    DocumentAnalysis,
    Span,
    ValueState,
)
from textnav.terms import FieldSpec
from textnav.ui.viewer import location, render_viewer

SHOW_LABEL = "Показать в документе"
PANEL_HEIGHT = 620

GROUPS = (
    (ChangeStatus.APPLIED, "Применённые изменения"),
    (ChangeStatus.NOT_YET_EFFECTIVE, "Подписанные, но не вступившие в силу"),
    (ChangeStatus.PROPOSAL, "Несогласованные предложения"),
    (ChangeStatus.NEEDS_REVIEW, "Требуют проверки"),
)
STATUS_LABELS = {
    ContractStatus.IN_FORCE: "Действует",
    ContractStatus.NOT_IN_FORCE: "Не действует на дату проверки",
    ContractStatus.NEEDS_REVIEW: "Требует проверки",
}
OTHER_ALERTS = (
    AlertCode.UNRECOGNIZED_CHANGE,
    AlertCode.EMPTY_AMENDMENT,
    AlertCode.SUPPLIER_MISMATCH,
)

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>|~$])")


def render_details(result: AnalysisResult, registry: tuple[FieldSpec, ...]) -> None:
    st.subheader("Детали договора")
    numbers = [view.number for view in result.contracts]
    number = st.selectbox("Договор", numbers, key="details_contract")
    view = next(v for v in result.contracts if v.number == number)
    documents = _documents(view)

    viewer_key = f"viewer::{view.number}"
    shown = st.session_state.get(viewer_key)
    if shown is None or shown.doc_id not in documents:
        st.session_state[viewer_key] = _default_citation(view, registry)

    # The details scroll inside a fixed-height block, so the source stays next to any quote.
    details_column, source_column = st.columns([3, 2], gap="large")
    with details_column, st.container(height=PANEL_HEIGHT, border=False):
        _render_status(view)
        for spec in registry:
            _render_term(view, spec, documents, viewer_key)
        _render_changes(view, documents, registry, viewer_key)
        _render_other_alerts(view, documents, viewer_key)
    with source_column:
        citation = st.session_state[viewer_key]
        render_viewer(documents[citation.doc_id].source, citation)


def quote_markdown(text: str, citation: Citation) -> str:
    """The cited sentence with the value in bold; document text is markdown-escaped."""
    if citation.value_start is None:
        return f"«{_md(text[citation.start : citation.end])}»"
    before = _md(text[citation.start : citation.value_start])
    value = _md(text[citation.value_start : citation.value_end])
    after = _md(text[citation.value_end : citation.end])
    return f"«{before}**{value}**{after}»"


# --- sections -------------------------------------------------------------------


def _render_status(view: ContractView) -> None:
    supplier = _md(view.supplier.value) if view.supplier.value else "нет данных"
    status = f"{STATUS_LABELS[view.status]}: {lower_first(view.status_reason)}."
    st.markdown(f"**Договор {_md(view.number)}**, поставщик: {supplier}.  \n{status}")


def _render_term(
    view: ContractView,
    spec: FieldSpec,
    documents: dict[str, DocumentAnalysis],
    viewer_key: str,
) -> None:
    term = view.terms[spec.name]
    effective = term.effective
    lines = [f"**{spec.label}: {value_text(effective)}**"]
    if effective.state is ValueState.VALUE:
        basis = documents[effective.source_doc_id]
        lines.append(f"Основание: {document_label(basis)} (`{basis.source.filename}`).")
    elif effective.state is ValueState.NOT_IN_FORCE:
        if term.applied.state is ValueState.VALUE:
            lines.append(f"По тексту документов: {value_text(term.applied)}.")
    else:
        lines.append(f"{_capitalize(effective.reason)}.")
        if effective.state is ValueState.NEEDS_REVIEW and term.applied.state is ValueState.VALUE:
            lines.append(f"Последнее подтверждённое значение: {value_text(term.applied)}.")
    st.markdown("  \n".join(lines))

    shown = effective.citations or term.applied.citations
    for index, citation in enumerate(shown):
        _quote(citation, documents, viewer_key, f"{view.number}-{spec.name}-{index}")

    if effective.state is ValueState.VALUE and term.changed_by:
        st.markdown(f"По договору: {value_text(term.original)}.")
        for index, citation in enumerate(term.original.citations):
            _quote(citation, documents, viewer_key, f"{view.number}-{spec.name}-original-{index}")


def _render_changes(
    view: ContractView,
    documents: dict[str, DocumentAnalysis],
    registry: tuple[FieldSpec, ...],
    viewer_key: str,
) -> None:
    labels = {spec.name: spec.label for spec in registry}
    for status, title in GROUPS:
        st.markdown(f"**{title}**")
        changes = [change for change in view.change_docs if change.status is status]
        if not changes:
            st.caption("Нет.")
            continue
        for change in changes:
            analysis = change.analysis
            values = ", ".join(
                f"{lower_first(labels.get(name, name))} → {describe_extraction(extraction)}"
                for name, extraction in change.changes.items()
            )
            line = (
                f"{document_label(analysis)} (`{analysis.source.filename}`): "
                f"{lower_first(change.reason)}."
            )
            st.markdown(f"{line} Изменения: {values}." if values else line)
            if status is ChangeStatus.APPLIED:
                continue  # their quotes are shown with the effective values above
            for name, extraction in change.changes.items():
                for index, citation in enumerate(extraction.citations[:1]):
                    key = f"{view.number}-{analysis.source.doc_id}-{name}-{index}"
                    _quote(citation, documents, viewer_key, key)


def _render_other_alerts(
    view: ContractView, documents: dict[str, DocumentAnalysis], viewer_key: str
) -> None:
    alerts = [alert for alert in view.alerts if alert.code in OTHER_ALERTS]
    if not alerts:
        return
    st.markdown("**Другие предупреждения**")
    for index, alert in enumerate(alerts):
        st.markdown(f"- {_md(alert.message)}")
        for citation in alert.citations[:1]:
            _quote(citation, documents, viewer_key, f"{view.number}-alert-{index}")


# --- helpers --------------------------------------------------------------------


def _quote(
    citation: Citation, documents: dict[str, DocumentAnalysis], viewer_key: str, key: str
) -> None:
    doc = documents[citation.doc_id].source
    st.markdown(f"> {quote_markdown(doc.text, citation)}\n>\n> {location(doc, citation)}")
    st.button(
        SHOW_LABEL,
        key=f"show::{key}",
        type="tertiary",
        on_click=_show,
        args=(viewer_key, citation),
    )


def _show(viewer_key: str, citation: Citation) -> None:
    st.session_state[viewer_key] = citation


def _default_citation(view: ContractView, registry: tuple[FieldSpec, ...]) -> Citation:
    for spec in registry:
        term = view.terms[spec.name]
        citations = term.effective.citations or term.applied.citations
        if citations:
            return citations[0]
    contract = view.contracts[0].source
    title = contract.paragraphs[0]
    return cite(contract, title, Span(title.start, title.end))


def _documents(view: ContractView) -> dict[str, DocumentAnalysis]:
    documents = {analysis.source.doc_id: analysis for analysis in view.contracts}
    documents |= {change.analysis.source.doc_id: change.analysis for change in view.change_docs}
    return documents


def _md(text: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]
