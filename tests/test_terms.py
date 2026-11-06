import re
from datetime import date
from decimal import Decimal

import pytest

from tests.builders import make_doc
from textnav.analyze import analyze_document
from textnav.ingest import read_document
from textnav.model import DocumentAnalysis
from textnav.model import ExtractionState as State
from textnav.terms import DELIVERY_DATE, TERM_REGISTRY, TOTAL_COST, FieldSpec, rule

CONTRACT_HEADER = "ДОГОВОР ПОСТАВКИ № A-1\nСтатус: подписан обеими сторонами 01.02.2026.\n"
AMENDMENT_HEADER = (
    "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ A-1\n"
    "Статус: подписано обеими сторонами 01.03.2026.\n"
    "Покупатель: ООО «А». Поставщик: ООО «Б».\n"
)


def _contract(body: str) -> DocumentAnalysis:
    return analyze_document(make_doc(CONTRACT_HEADER + body))


def _amendment(body: str) -> DocumentAnalysis:
    return analyze_document(make_doc(AMENDMENT_HEADER + body))


def _value_text(analysis: DocumentAnalysis, field: str) -> list[str]:
    text = analysis.source.text
    return [
        text[c.value_start : c.value_end]
        for c in analysis.terms[field].citations
        if c.value_start is not None
    ]


def _assert_citations_exact(analysis: DocumentAnalysis) -> None:
    doc = analysis.source
    citations = [c for e in analysis.terms.values() for c in e.citations]
    citations += [clause.citation for clause in analysis.change_clauses]
    for c in citations:
        assert doc.text[c.start : c.end] == c.quote
        paragraph = doc.paragraphs[c.paragraph]
        assert paragraph.start <= c.start < c.end <= paragraph.end
        if c.value_start is not None:
            assert c.start <= c.value_start < c.value_end <= c.end


# --- sample documents -------------------------------------------------------

SAMPLES = {
    "01_contract.txt": (Decimal("1200000"), date(2026, 4, 15)),
    "02_amendment_signed.txt": (Decimal("1380000"), date(2026, 4, 30)),
    "03_contract.txt": (Decimal("840000"), date(2026, 3, 20)),
    "04_contract.txt": (None, date(2026, 4, 30)),
    "05_supplier_email.txt": (None, date(2026, 3, 27)),
    "06_amendment_draft.txt": (Decimal("1450000"), date(2026, 5, 10)),
}


@pytest.fixture(scope="module")
def samples(source_files) -> dict[str, DocumentAnalysis]:
    return {name: analyze_document(read_document(name, data)) for name, data in source_files}


@pytest.mark.parametrize("filename", sorted(SAMPLES))
def test_sample_terms(filename, samples):
    analysis = samples[filename]
    cost, delivery = SAMPLES[filename]

    assert analysis.terms["total_cost"].value == cost
    assert analysis.terms["delivery_date"].value == delivery
    assert analysis.terms["delivery_date"].state == State.FOUND
    _assert_citations_exact(analysis)


def test_advance_payment_is_not_the_total_cost(samples):
    analysis = samples["03_contract.txt"]

    assert analysis.terms["total_cost"].state == State.FOUND
    assert _value_text(analysis, "total_cost") == ["840 000 (восемьсот сорок тысяч) рублей"]


def test_payment_deadline_is_not_the_delivery_date(samples):
    assert _value_text(samples["03_contract.txt"], "delivery_date") == ["20.03.2026"]


def test_budget_limit_is_not_the_cost(samples):
    cost = samples["04_contract.txt"].terms["total_cost"]

    assert cost.state == State.STATED_ABSENT
    assert cost.value is None
    assert any("не указано" in c.quote for c in cost.citations)
    assert not any("600 000" in c.quote for c in cost.citations)


def test_contracts_have_no_change_clauses(samples):
    assert samples["01_contract.txt"].change_clauses == ()


def test_signed_amendment_change_clauses_target_contract_clauses(samples):
    clauses = samples["02_amendment_signed.txt"].change_clauses

    assert [(c.target_clause, c.fields) for c in clauses] == [
        ("2.1", ("total_cost",)),
        ("3.1", ("delivery_date",)),
    ]


def test_letter_proposal_takes_the_new_date_only(samples):
    analysis = samples["05_supplier_email.txt"]

    assert _value_text(analysis, "delivery_date") == ["27.03.2026"]
    assert analysis.terms["total_cost"].state == State.NOT_FOUND
    assert len(analysis.change_clauses) == 1


def test_draft_proposals_are_extracted(samples):
    clauses = samples["06_amendment_draft.txt"].change_clauses

    assert [c.fields for c in clauses] == [("total_cost",), ("delivery_date",)]


# --- contract: cost wording variants ----------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Цена договора составляет 500 000 рублей.",
        "Общая сумма договора равна 500 000 руб.",
        "Стоимость товара — 500 000 ₽.",
        "Общая стоимость поставки: 500 000 рублей, включая НДС.",
        "Итоговая стоимость договора составляет 500 000,00 руб.",
        "Общая стоимость поставки составляет 500 000 рублей, включая аванс 150 000 рублей.",
        "Договор заключен на общую сумму 500 000 рублей.",
    ],
)
def test_contract_cost_variants(sentence):
    cost = _contract(f"2.1. {sentence}").terms["total_cost"]

    assert (cost.state, cost.value) == (State.FOUND, Decimal("500000"))


@pytest.mark.parametrize(
    "sentence",
    [
        "Авансовый платеж составляет 150 000 рублей.",
        "Лимит закупки по бюджету — 600 000 рублей.",
        "Неустойка составляет 0,1% стоимости.",
        "Аванс в размере 30% от общей стоимости составляет 150 000 рублей.",
        "Себестоимость составляет 400 000 рублей.",
    ],
)
def test_contract_cost_distractors(sentence):
    assert _contract(f"2.2. {sentence}").terms["total_cost"].state == State.NOT_FOUND


def test_cost_with_advance_in_next_clause():
    analysis = _contract(
        "2.1. Общая стоимость составляет 900 000 рублей.\n"
        "2.2. Авансовый платеж составляет 270 000 рублей и входит в общую стоимость."
    )

    assert analysis.terms["total_cost"].value == Decimal("900000")


@pytest.mark.parametrize(
    "sentence", ["Стоимость определяется спецификацией.", "Цена договора не установлена."]
)
def test_contract_cost_stated_absent(sentence):
    assert _contract(f"2.1. {sentence}").terms["total_cost"].state == State.STATED_ABSENT


def test_contract_cost_in_words_only_is_unparsed():
    cost = _contract("2.1. Общая стоимость составляет один миллион рублей.").terms["total_cost"]

    assert cost.state == State.UNPARSED
    assert cost.citations


def test_contract_with_two_different_costs_is_ambiguous():
    analysis = _contract(
        "2.1. Общая стоимость составляет 100 рублей.\n2.2. Цена договора составляет 200 рублей."
    )

    assert analysis.terms["total_cost"].state == State.AMBIGUOUS
    assert len(analysis.terms["total_cost"].citations) == 2


def test_contract_repeating_the_same_cost_is_found():
    analysis = _contract(
        "2.1. Общая стоимость составляет 100 рублей.\n9.1. Цена договора составляет 100 рублей."
    )

    assert analysis.terms["total_cost"].state == State.FOUND
    assert len(analysis.terms["total_cost"].citations) == 2


# --- contract: delivery wording variants ------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Поставщик обязуется поставить товар не позднее 30.04.2026.",
        "Поставка осуществляется до 30.04.2026.",
        "Срок поставки — не позднее 30.04.2026.",
        "Срок поставки: 30 апреля 2026 г.",
        "Поставщик обязуется осуществить поставку по 30.04.2026.",
        "Поставка осуществляется в период с 01.04.2026 по 30.04.2026.",
        "Поставщик обязуется поставить товар по адресу склада не позднее 30.04.2026.",
        "Поставка до 30.04.2026, приемка — в течение 5 рабочих дней.",
    ],
)
def test_contract_delivery_variants(sentence):
    delivery = _contract(f"3.1. {sentence}").terms["delivery_date"]

    assert (delivery.state, delivery.value) == (State.FOUND, date(2026, 4, 30))


@pytest.mark.parametrize(
    "sentence",
    [
        "Оплата производится не позднее 10.04.2026.",
        "Дата приемки может отличаться от даты поставки.",
        "Этот срок является сроком оплаты, а не поставки.",
        "Гарантийный срок — до 30.04.2027.",
        "Неустойка за просрочку поставки начисляется с 01.05.2026.",
        "Договор поставки действует до 31.12.2026.",
        "Настоящий договор поставки вступает в силу с 01.02.2026 и действует до 31.12.2026.",
    ],
)
def test_contract_delivery_distractors(sentence):
    assert _contract(f"3.2. {sentence}").terms["delivery_date"].state == State.NOT_FOUND


def test_delivery_with_payment_deadline_in_next_clause():
    analysis = _contract(
        "3.1. Поставщик обязуется поставить комплектующие не позднее 20.03.2026.\n"
        "3.2. Оплата производится не позднее 10.04.2026. Этот срок является сроком оплаты."
    )

    assert analysis.terms["delivery_date"].value == date(2026, 3, 20)


@pytest.mark.parametrize(
    "sentence",
    [
        "Поставка осуществляется не позднее 31.04.2026.",
        "Срок поставки — в течение 30 календарных дней с даты заявки.",
    ],
)
def test_contract_delivery_unreadable_value_is_unparsed(sentence):
    assert _contract(f"3.1. {sentence}").terms["delivery_date"].state == State.UNPARSED


def test_contract_delivery_stated_absent():
    analysis = _contract("3.1. Срок поставки в тексте договора не установлен.")

    assert analysis.terms["delivery_date"].state == State.STATED_ABSENT


# --- change documents -------------------------------------------------------


@pytest.mark.parametrize(
    ("clause", "field", "value"),
    [
        (
            "Пункт 2.1 договора изложить в следующей редакции: "
            "«Цена договора составляет 700 000 рублей».",
            "total_cost",
            Decimal("700000"),
        ),
        (
            "Пункт 2.1 изложить в следующей редакции: "
            "«Цена включает НДС. Общая стоимость составляет 1 380 000 рублей».",
            "total_cost",
            Decimal("1380000"),
        ),
        ("Увеличить общую стоимость до 900 000 рублей.", "total_cost", Decimal("900000")),
        ("Изменить срок поставки с 20.03.2026 на 27.03.2026.", "delivery_date", date(2026, 3, 27)),
        ("Срок поставки переносится на 27.03.2026.", "delivery_date", date(2026, 3, 27)),
        ("Продлить срок поставки до 15.05.2026.", "delivery_date", date(2026, 5, 15)),
    ],
)
def test_amendment_change_values(clause, field, value):
    term = _amendment(f"1. {clause}").terms[field]

    assert (term.state, term.value) == (State.FOUND, value)


@pytest.mark.parametrize(
    ("clause", "field"),
    [
        ("Увеличить общую стоимость на 100 000 рублей.", "total_cost"),
        ("Изменить срок поставки до конца апреля.", "delivery_date"),
        (
            "Пункт 2.1 договора изложить в следующей редакции: "
            "«Стоимость определяется спецификацией».",
            "total_cost",
        ),
    ],
)
def test_amendment_change_without_recognizable_value_is_unparsed(clause, field):
    analysis = _amendment(f"1. {clause}")

    assert analysis.terms[field].state == State.UNPARSED
    assert analysis.change_clauses[0].fields == (field,)


def test_clause_target_is_recorded_even_without_known_fields():
    analysis = _amendment(
        "1. Пункт 4.1 изложить в следующей редакции: «Неустойка составляет 0,2% стоимости»."
    )

    assert analysis.terms["total_cost"].state == State.NOT_FOUND
    assert [(c.target_clause, c.fields) for c in analysis.change_clauses] == [("4.1", ())]


def test_amendment_values_outside_change_clauses_are_ignored():
    analysis = _amendment(
        "Общая стоимость договора составляет 1 200 000 рублей.\n"
        "1. Изменить общую стоимость на 1 300 000 рублей."
    )

    assert analysis.terms["total_cost"].value == Decimal("1300000")


def test_amendment_unchanged_terms_are_not_found():
    analysis = _amendment("1. Остальные условия, включая срок поставки, остаются без изменений.")

    assert analysis.terms["delivery_date"].state == State.NOT_FOUND
    assert analysis.change_clauses == ()


def test_amendment_with_two_different_new_values_is_ambiguous():
    analysis = _amendment(
        "1. Изменить срок поставки на 27.03.2026.\n2. Изменить срок поставки на 28.03.2026."
    )

    assert analysis.terms["delivery_date"].state == State.AMBIGUOUS


def test_amendment_value_plus_unrecognized_change_of_same_field_is_ambiguous():
    analysis = _amendment(
        "1. Изменить срок поставки на 27.03.2026.\n2. Изменить срок поставки до конца мая."
    )

    assert analysis.terms["delivery_date"].state == State.AMBIGUOUS


def test_titles_and_header_lines_are_not_change_clauses():
    analysis = analyze_document(
        make_doc(
            "ПИСЬМО О ПЕРЕНОСЕ СРОКА ПОСТАВКИ\n"
            "Тема: перенос срока поставки по договору A-1\n"
            "Предлагаем перенести срок поставки на 27.03.2026."
        )
    )

    assert analysis.terms["delivery_date"].value == date(2026, 3, 27)
    assert len(analysis.change_clauses) == 1


# --- extensibility ----------------------------------------------------------


def _parse_percent(text: str) -> Decimal | None:
    match = re.search(r"\d+(?:,\d+)?", text)
    return Decimal(match.group().replace(",", ".")) if match else None


PENALTY_RATE = FieldSpec(
    name="penalty_rate",
    label="Неустойка",
    parse=_parse_percent,
    rules=(rule("statement", r"неустойк\w*.{0,40}?составляет\s+(?P<value>\d+(?:,\d+)?\s*%)"),),
    veto=re.compile(r"(?!)"),
    mention=re.compile(r"неустойк", re.IGNORECASE),
    value_hint=re.compile(r"%"),
    absent=re.compile(r"не\s+установлен", re.IGNORECASE),
    in_table=False,
)


def test_new_field_is_extracted_without_engine_changes():
    registry = (*TERM_REGISTRY, PENALTY_RATE)

    contract = analyze_document(
        make_doc(CONTRACT_HEADER + "4.1. Неустойка за просрочку составляет 0,1% в день."), registry
    )
    amendment = analyze_document(
        make_doc(AMENDMENT_HEADER + "1. Пункт 4.1 изложить: «Неустойка составляет 0,2% в день»."),
        registry,
    )

    assert contract.terms["penalty_rate"].value == Decimal("0.1")
    assert amendment.terms["penalty_rate"].value == Decimal("0.2")
    assert amendment.change_clauses[0].fields == ("penalty_rate",)


def test_default_registry_has_cost_and_delivery():
    assert [spec.name for spec in TERM_REGISTRY] == [TOTAL_COST.name, DELIVERY_DATE.name]
