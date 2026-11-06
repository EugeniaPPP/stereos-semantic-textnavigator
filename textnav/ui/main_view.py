"""Main screen: upload, check date, contracts table with a delivery filter, attention list.

The whole analysis is recomputed on every Streamlit rerun from the current files and dates,
so changing the file set or a date never leaves stale results.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from textnav.formatting import (
    NEEDS_REVIEW_TEXT,
    NO_DATA_TEXT,
    NOT_IN_FORCE_TEXT,
    describe_extraction,
    document_label,
    format_date,
    lower_first,
    value_text,
)
from textnav.model import (
    AlertCode,
    AnalysisResult,
    AttentionItem,
    AttentionReason,
    ChangeStatus,
    ContractStatus,
    ContractView,
)
from textnav.pipeline import analyze, contracts_with_delivery_before, unagreed_changes
from textnav.terms import TERM_REGISTRY, FieldSpec
from textnav.ui.details_view import render_details

COL_NUMBER = "Договор"
COL_SUPPLIER = "Поставщик"
COL_UNAGREED = "Несогласованные изменения"
COL_STATUS = "Статус и предупреждения"

NBSP = "\u00a0"  # keeps "1 000 000 ₽" and "Нет данных" on one line in table cells
NO_DATA = NO_DATA_TEXT
NEEDS_REVIEW = NEEDS_REVIEW_TEXT
NOT_IN_FORCE = NOT_IN_FORCE_TEXT

REASON_LABELS = {
    AttentionReason.ORPHAN: "исходный договор не загружен",
    AttentionReason.UNLINKED: "связь с договором не установлена",
    AttentionReason.UNKNOWN_TYPE: "тип документа не распознан",
    AttentionReason.READ_ERROR: "файл не прочитан",
    AttentionReason.DUPLICATE: "повторная загрузка",
}
CHANGE_STATUS_LABELS = {
    ChangeStatus.APPLIED: "подписано обеими сторонами и вступило в силу",
    ChangeStatus.NOT_YET_EFFECTIVE: "подписано, но ещё не вступило в силу",
    ChangeStatus.PROPOSAL: "несогласованное предложение",
    ChangeStatus.NEEDS_REVIEW: "требует проверки",
}

# Reliability of a value is the one emphasized visual signal of the table.
_REVIEW_STYLE = "background-color: #FCEFD4; color: #5A3A00; font-weight: 600"
_QUIET_STYLE = "color: #5C6670; font-style: italic"


# --- pure helpers (unit-tested) -----------------------------------------------


def unagreed_text(view: ContractView, registry: tuple[FieldSpec, ...]) -> str:
    """One entry per document: "Письмо от 31.12.2030: срок поставки → 15.01.2031"."""
    labels = {spec.name: spec.label for spec in registry}
    changes = {change.analysis.source.doc_id: change for change in view.change_docs}
    by_document: dict[str, list[str]] = {}
    for alert in unagreed_changes(view):
        items = by_document.setdefault(alert.doc_id, [])
        if alert.field is None:
            items.append("значения не распознаны")
        else:
            value = describe_extraction(changes[alert.doc_id].changes[alert.field])
            items.append(f"{lower_first(labels.get(alert.field, alert.field))} → {value}")
    return "; ".join(
        f"{document_label(changes[doc_id].analysis)}: {', '.join(items)}"
        for doc_id, items in by_document.items()
    )


def status_text(view: ContractView) -> str:
    messages = [
        alert.message for alert in view.alerts if alert.code is not AlertCode.CHANGE_PROPOSAL
    ]
    if not messages and view.status is ContractStatus.IN_FORCE:
        return "Действует"
    return "; ".join(messages)


def table_rows(
    contracts: list[ContractView] | tuple[ContractView, ...], registry: tuple[FieldSpec, ...]
) -> list[dict[str, str]]:
    rows = []
    for view in contracts:
        row = {COL_NUMBER: view.number, COL_SUPPLIER: view.supplier.value or NO_DATA}
        for spec in registry:
            if spec.in_table:
                row[spec.label] = value_text(view.terms[spec.name].effective).replace(" ", NBSP)
        row[COL_UNAGREED] = unagreed_text(view, registry)
        row[COL_STATUS] = status_text(view)
        rows.append(row)
    return rows


def preload_files(directory: str | None) -> list[tuple[str, bytes]]:
    """Development helper: all ``*.txt`` from a directory, as if uploaded (STN_PRELOAD_DIR)."""
    if not directory or not Path(directory).is_dir():
        return []
    return [(path.name, path.read_bytes()) for path in sorted(Path(directory).glob("*.txt"))]


# --- rendering ----------------------------------------------------------------


def render(
    default_check_date: date,
    preload_dir: str | None = None,
    registry: tuple[FieldSpec, ...] = TERM_REGISTRY,
) -> None:
    st.title("Semantic TextNavigator")
    st.caption(
        "Действующие сумма и срок поставки по договорам на выбранную дату. "
        "Каждое значение подтверждено цитатой из исходного документа."
    )

    upload_column, date_column = st.columns([3, 1])
    with upload_column:
        uploaded = st.file_uploader(
            "Документы в формате TXT",
            type=["txt"],
            accept_multiple_files=True,
            help=(
                "Договоры, допсоглашения, проекты изменений и письма. "
                "Имена и порядок файлов не важны."
            ),
        )
    with date_column:
        check_date = st.date_input(
            "Дата проверки", value=default_check_date, format="DD.MM.YYYY", key="check_date"
        )

    preloaded = preload_files(preload_dir)
    if preloaded:
        st.caption(f"Режим разработки: из папки {preload_dir} подгружено файлов: {len(preloaded)}.")
    files = preloaded + [(file.name, file.getvalue()) for file in uploaded or []]
    if not files:
        st.info(
            "Загрузите TXT-файлы договоров, допсоглашений и писем — здесь появится таблица "
            "действующих условий. Таблица пересчитывается при каждом изменении файлов или даты."
        )
        return

    if check_date is None:
        st.info("Укажите дату проверки: условия договоров определяются на конкретную дату.")
        return
    try:
        result = analyze(files, check_date, registry)
    except Exception as error:  # last resort: the page explains instead of showing a traceback
        st.error(
            f"Не удалось обработать документы: внутренняя ошибка ({type(error).__name__}). "
            "Уберите последний добавленный файл и повторите; если ошибка останется, "
            "сообщите разработчику, какие файлы были загружены."
        )
        return
    st.caption(
        f"Файлов: {len(files)}. Договоров: {len(result.contracts)}. "
        f"Документов, требующих внимания: {len(result.attention)}."
    )
    _render_contracts(result, registry)
    if result.contracts:
        render_details(result, registry)
    _render_attention(result, registry)


def _render_contracts(result: AnalysisResult, registry: tuple[FieldSpec, ...]) -> None:
    st.subheader(f"Договоры на {format_date(result.check_date)}")
    if not result.contracts:
        st.info("Среди загруженных документов нет договоров. Остальные документы перечислены ниже.")
        return

    filter_column, filter_date_column, _ = st.columns([2, 1, 2], vertical_alignment="bottom")
    with filter_column:
        enabled = st.checkbox("Только со сроком поставки раньше даты", key="filter_enabled")
    with filter_date_column:
        before = st.date_input(
            "Срок поставки раньше",
            value=result.check_date,
            format="DD.MM.YYYY",
            key="filter_date",
            disabled=not enabled,
        )

    contracts: list[ContractView] | tuple[ContractView, ...] = result.contracts
    if enabled and before is None:
        st.caption("Укажите дату, чтобы применить фильтр.")
    elif enabled:
        contracts, excluded = contracts_with_delivery_before(result, before)
        note = f"Срок поставки раньше {format_date(before)}: договоров {len(contracts)}."
        if excluded:
            note += f" Без достоверного срока, в фильтре не участвуют: {excluded}."
        st.caption(note)
    if not contracts:
        st.info(f"Нет договоров со сроком поставки раньше {format_date(before)}.")
        return

    value_columns = [spec.label for spec in registry if spec.in_table]
    table = pd.DataFrame(table_rows(contracts, registry))
    # A static table: every warning is read in full, nothing is cut off as in a grid.
    styled = table.style.map(_value_style, subset=value_columns)
    st.table(styled, hide_index=True, border="horizontal")


def _value_style(text: str) -> str:
    text = text.replace(NBSP, " ")
    if text == NEEDS_REVIEW:
        return _REVIEW_STYLE
    if text in (NO_DATA, NOT_IN_FORCE):
        return _QUIET_STYLE
    return ""


def _render_attention(result: AnalysisResult, registry: tuple[FieldSpec, ...]) -> None:
    st.subheader("Документы, требующие внимания")
    if not result.attention:
        st.caption("Таких документов нет: все документы распознаны и связаны с договорами.")
        return
    for item in result.attention:
        st.markdown(_attention_markdown(item, registry))


def _attention_markdown(item: AttentionItem, registry: tuple[FieldSpec, ...]) -> str:
    lines = [f"**`{item.filename}`**: {REASON_LABELS[item.reason]}. {item.message}"]
    if item.change is not None:
        change = item.change
        labels = {spec.name: spec.label for spec in registry}
        status = CHANGE_STATUS_LABELS[change.status]
        lines.append(f"{document_label(change.analysis)}: {status} ({lower_first(change.reason)}).")
        if change.changes:
            values = "; ".join(
                f"{labels.get(name, name)} → {describe_extraction(extraction)}"
                for name, extraction in change.changes.items()
            )
            lines.append(f"Изменения в документе: {values}.")
    return "  \n".join(lines)
