"""Helpers that build synthetic documents for tests (texts follow the sample format)."""

from datetime import date

from textnav.analyze import analyze_document
from textnav.ingest import read_document
from textnav.linking import link
from textnav.model import AttentionItem, ContractView, DocumentAnalysis, SourceDocument
from textnav.resolve import resolve_groups

CHECK_DATE = date(2026, 3, 10)


def make_doc(text: str, filename: str = "doc.txt") -> SourceDocument:
    result = read_document(filename, text.encode("utf-8"))
    assert isinstance(result, SourceDocument), result
    return result


def _lines(*lines: str | None) -> str:
    return "\n".join(line for line in lines if line)


def contract_text(
    number: str = "A-1",
    status: str | None = "подписан обеими сторонами 01.02.2026",
    cost: str = "2.1. Общая стоимость поставки составляет 1 000 000 рублей, включая НДС.",
    delivery: str = "3.1. Поставщик обязуется поставить товар не позднее 30.04.2026.",
    supplier: str = "ООО «Б»",
    extra: tuple[str, ...] = (),
    doc_date: str = "01.02.2026",
) -> str:
    return _lines(
        f"ДОГОВОР ПОСТАВКИ № {number}",
        f"Дата: {doc_date}",
        f"Статус: {status}." if status else None,
        f"1.1. Покупатель: ООО «А». Поставщик: {supplier}.",
        cost,
        delivery,
        *extra,
    )


def cost_change(amount: str) -> str:
    return (
        "Пункт 2.1 договора изложить в следующей редакции: "
        f"«Общая стоимость поставки составляет {amount}, включая НДС»."
    )


def delivery_change(day: str) -> str:
    return (
        "Пункт 3.1 договора изложить в следующей редакции: "
        f"«Поставщик обязуется поставить товар не позднее {day}»."
    )


def amendment_text(
    number: str = "1",
    contract: str = "A-1",
    status: str | None = "подписано обеими сторонами 01.03.2026",
    changes: tuple[str, ...] = (cost_change("1 100 000 рублей"),),
    effective: str | None = "Настоящее соглашение вступает в силу 01.03.2026.",
    title: str = "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ",
    supplier: str = "ООО «Б»",
    doc_date: str = "01.03.2026",
) -> str:
    clauses = [f"{i}. {text}" for i, text in enumerate(changes, start=1)]
    if effective:
        clauses.append(f"{len(clauses) + 1}. {effective}")
    return _lines(
        f"{title} № {number} К ДОГОВОРУ {contract}",
        f"Дата: {doc_date}",
        f"Статус: {status}." if status else None,
        f"Покупатель: ООО «А». Поставщик: {supplier}.",
        *clauses,
    )


def draft_text(
    number: str = "2",
    contract: str = "A-1",
    status: str | None = "проект на согласовании, не подписан ни одной стороной",
    changes: tuple[str, ...] = ("Предлагается изменить срок поставки на 10.05.2026.",),
    doc_date: str = "06.03.2026",
) -> str:
    return amendment_text(
        number=number,
        contract=contract,
        status=status,
        changes=changes,
        effective=None,
        title="ПРОЕКТ ДОПОЛНИТЕЛЬНОГО СОГЛАШЕНИЯ",
        doc_date=doc_date,
    )


def letter_text(
    contract: str = "A-1",
    body: str = "Предлагаем перенести срок поставки с 30.04.2026 на 15.05.2026.",
    doc_date: str = "05.03.2026",
) -> str:
    return _lines(
        "ПИСЬМО ПОСТАВЩИКА",
        f"Дата: {doc_date}",
        "От: ООО «Б»",
        "Кому: ООО «А»",
        f"Тема: договор {contract}",
        body,
    )


def analyze_texts(*texts: str) -> list[DocumentAnalysis]:
    return [analyze_document(make_doc(text, f"doc{i}.txt")) for i, text in enumerate(texts)]


def resolve_texts(
    *texts: str, check_date: date = CHECK_DATE
) -> tuple[list[ContractView], list[AttentionItem]]:
    groups, attention = link(analyze_texts(*texts))
    views, orphans = resolve_groups(groups, check_date)
    return views, attention + orphans


def resolve_one(*texts: str, check_date: date = CHECK_DATE) -> ContractView:
    views, _ = resolve_texts(*texts, check_date=check_date)
    assert len(views) == 1, views
    return views[0]
