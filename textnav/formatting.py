"""Russian formatting of values and document names for messages and the UI."""

from datetime import date
from decimal import Decimal
from typing import Any

from textnav.model import DocType, DocumentAnalysis


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
    """Short human name: "Допсоглашение № 1 от 01.03.2026", "Письмо от 05.03.2026"."""
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
