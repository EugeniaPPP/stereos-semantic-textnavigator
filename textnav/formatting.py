"""Russian formatting of values and document names for messages and the UI."""

from datetime import date
from decimal import Decimal
from typing import Any

from textnav.model import DocType, DocumentAnalysis, Extraction, ExtractionState


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def format_money(value: Decimal) -> str:
    integer, _, fraction = f"{value:.2f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", " ")
    return f"{grouped} ₽" if fraction == "00" else f"{grouped},{fraction} ₽"


def format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return format_money(value)
    if isinstance(value, date):
        return format_date(value)
    return str(value)


def document_label(analysis: DocumentAnalysis) -> str:
    """Short human name: "Допсоглашение № 3 от 31.12.2030", "Письмо от 31.12.2030"."""
    meta = analysis.meta
    number = f" № {meta.number.value}" if meta.number.value else ""
    dated = f" от {format_date(meta.doc_date.value)}" if meta.doc_date.value else ""
    match meta.doc_type:
        case DocType.CONTRACT:
            return f"Договор {meta.number.value}" if meta.number.value else "Договор"
        case DocType.AMENDMENT:
            return f"Допсоглашение{number}{dated}"
        case DocType.AMENDMENT_DRAFT:
            return f"Проект допсоглашения{number}{dated}"
        case DocType.LETTER:
            return f"Письмо{dated}"
        case _:
            return f"Документ «{analysis.source.filename}»"


def describe_extraction(extraction: Extraction) -> str:
    """Value of a change for messages: the value itself or why it is not shown."""
    if extraction.state is ExtractionState.FOUND:
        return format_value(extraction.value)
    if extraction.state is ExtractionState.AMBIGUOUS:
        return "несколько разных значений"
    return "значение не распознано"


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]
