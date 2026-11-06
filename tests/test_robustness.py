"""Result independence from file names and order; reaction to edited and new documents.

The "meeting rehearsal" tests mirror docs/TASK.md: one field of a sample file is changed
and a new contract of the same general format is uploaded.
"""

import random
from datetime import date
from decimal import Decimal

import pytest

from textnav.model import (
    AlertCode,
    AnalysisResult,
    AttentionReason,
    ChangeStatus,
    ContractView,
    ValueState,
)
from textnav.pipeline import analyze, contracts_with_delivery_before

CHECK_DATE = date(2026, 3, 10)

NEW_CONTRACT = """ДОГОВОР ПОСТАВКИ № STN-104
Дата: 03.03.2026
Статус: подписан обеими сторонами 03.03.2026.

1.1. Покупатель: ООО «СеверМет». Поставщик: АО «Новый Поставщик».
1.2. Предмет: поставка насосного оборудования.

2.1. Цена договора составляет 2 500 000 (два миллиона пятьсот тысяч) рублей, включая НДС.
2.2. Авансовый платеж — 500 000 рублей, входит в цену договора.

3.1. Срок поставки — не позднее «25» марта 2026 г.
3.2. Оплата производится не позднее 15.04.2026.
"""

NEW_AMENDMENT = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ STN-104
Дата: 06.03.2026
Статус: подписано обеими сторонами 06.03.2026.
Покупатель: ООО «СеверМет». Поставщик: АО «Новый Поставщик».

1. Срок поставки переносится на 31.03.2026.
2. Настоящее соглашение вступает в силу с момента подписания.
"""


def _project(result: AnalysisResult):
    """Everything except file names."""
    contracts = [
        (
            v.number,
            v.status,
            v.supplier.value,
            {
                n: (t.effective.state, t.effective.value, t.effective.source_doc_id)
                for n, t in v.terms.items()
            },
            [(c.analysis.source.doc_id, c.status) for c in v.change_docs],
            [(a.code, a.field, a.doc_id, a.message) for a in v.alerts],
        )
        for v in result.contracts
    ]
    attention = [
        (i.reason, i.analysis.source.doc_id if i.analysis else None) for i in result.attention
    ]
    return contracts, attention


def _view(result: AnalysisResult, number: str) -> ContractView:
    return {v.number: v for v in result.contracts}[number]


def _values(view: ContractView):
    return tuple(
        (view.terms[f].effective.state, view.terms[f].effective.value)
        for f in ("total_cost", "delivery_date")
    )


def _edit(files, filename: str, old: str, new: str):
    edited = []
    for name, data in files:
        if name == filename:
            text = data.decode("utf-8")
            assert old in text, (filename, old)
            data = text.replace(old, new).encode("utf-8")
        edited.append((name, data))
    return edited


# --- independence -------------------------------------------------------------


def test_upload_order_does_not_change_the_result(source_files):
    shuffled = list(source_files)
    random.Random(7).shuffle(shuffled)

    assert _project(analyze(shuffled, CHECK_DATE)) == _project(analyze(source_files, CHECK_DATE))


def test_renaming_files_does_not_change_the_result(source_files):
    renamed = [
        (f"upload_{i}_{name[::-1]}", data) for i, (name, data) in enumerate(reversed(source_files))
    ]

    assert _project(analyze(renamed, CHECK_DATE)) == _project(analyze(source_files, CHECK_DATE))


def test_windows_line_endings_do_not_change_the_result(source_files):
    crlf = [(name, data.replace(b"\n", b"\r\n")) for name, data in source_files]

    assert _project(analyze(crlf, CHECK_DATE)) == _project(analyze(source_files, CHECK_DATE))


def test_unreadable_file_does_not_block_the_others(source_files):
    result = analyze([*source_files, ("broken.txt", b"\x00\x01\x02")], CHECK_DATE)

    assert len(result.contracts) == 3
    assert [(i.reason, i.filename) for i in result.attention] == [
        (AttentionReason.READ_ERROR, "broken.txt")
    ]


def test_amendment_is_linked_when_its_contract_is_added_later(source_files):
    without_contract = [f for f in source_files if f[0] != "01_contract.txt"]

    before = analyze(without_contract, CHECK_DATE)
    after = analyze(source_files, CHECK_DATE)

    assert sorted(i.filename for i in before.attention if i.reason is AttentionReason.ORPHAN) == [
        "02_amendment_signed.txt",
        "06_amendment_draft.txt",
    ]
    assert "STN-101" not in [v.number for v in before.contracts]
    assert _values(_view(after, "STN-101")) == (
        (ValueState.VALUE, Decimal("1380000")),
        (ValueState.VALUE, date(2026, 4, 30)),
    )


# --- meeting rehearsal: one field changed -----------------------------------------


def test_changed_contract_amount_is_reflected(source_files):
    files = _edit(
        source_files,
        "03_contract.txt",
        "составляет 840 000 (восемьсот сорок тысяч)",
        "составляет 910 000",
    )

    assert _view(analyze(files, CHECK_DATE), "STN-102").terms[
        "total_cost"
    ].effective.value == Decimal("910000")


def test_changed_amendment_date_is_reflected(source_files):
    files = _edit(
        source_files, "02_amendment_signed.txt", "не позднее 30.04.2026", "не позднее 25.04.2026"
    )

    assert _view(analyze(files, CHECK_DATE), "STN-101").terms[
        "delivery_date"
    ].effective.value == date(2026, 4, 25)


def test_amendment_effective_after_check_date_is_pending(source_files):
    files = _edit(
        source_files,
        "02_amendment_signed.txt",
        "вступает в силу 01.03.2026",
        "вступает в силу 15.03.2026",
    )

    view = _view(analyze(files, CHECK_DATE), "STN-101")

    assert _values(view) == (
        (ValueState.VALUE, Decimal("1200000")),
        (ValueState.VALUE, date(2026, 4, 15)),
    )
    assert view.change_docs[0].status == ChangeStatus.NOT_YET_EFFECTIVE
    assert AlertCode.CHANGE_PENDING in [a.code for a in view.alerts]


def test_amendment_signed_after_check_date_is_pending(source_files):
    files = _edit(
        source_files,
        "02_amendment_signed.txt",
        "Статус: подписано обеими сторонами 01.03.2026",
        "Статус: подписано обеими сторонами 12.03.2026",
    )

    view = _view(analyze(files, CHECK_DATE), "STN-101")

    assert view.terms["total_cost"].effective.value == Decimal("1200000")


def test_amendment_marked_unsigned_needs_review(source_files):
    files = _edit(
        source_files,
        "02_amendment_signed.txt",
        "Статус: подписано обеими сторонами 01.03.2026.",
        "Статус: не подписано.",
    )

    view = _view(analyze(files, CHECK_DATE), "STN-101")

    assert [s for s, _ in _values(view)] == [ValueState.NEEDS_REVIEW, ValueState.NEEDS_REVIEW]
    assert view.terms["total_cost"].applied.value == Decimal("1200000")


def test_draft_marked_signed_needs_review(source_files):
    files = _edit(
        source_files,
        "06_amendment_draft.txt",
        "Статус: проект на согласовании, не подписан ни одной стороной.",
        "Статус: подписан обеими сторонами 08.03.2026.",
    )

    view = _view(analyze(files, CHECK_DATE), "STN-101")

    assert [s for s, _ in _values(view)] == [ValueState.NEEDS_REVIEW, ValueState.NEEDS_REVIEW]


def test_removed_amount_becomes_no_data(source_files):
    files = _edit(
        source_files,
        "03_contract.txt",
        "Общая стоимость поставки составляет 840 000 (восемьсот сорок тысяч) рублей, включая НДС.",
        "Общая стоимость определяется спецификацией.",
    )

    total = _view(analyze(files, CHECK_DATE), "STN-102").terms["total_cost"].effective

    assert (total.state, total.value) == (ValueState.NO_DATA, None)


def test_changed_contract_number_relinks_documents(source_files):
    files = _edit(source_files, "03_contract.txt", "№ STN-102", "№ STN-105")

    result = analyze(files, CHECK_DATE)

    assert [v.number for v in result.contracts] == ["STN-101", "STN-103", "STN-105"]
    assert [(i.reason, i.filename) for i in result.attention] == [
        (AttentionReason.ORPHAN, "05_supplier_email.txt")
    ]


# --- meeting rehearsal: a new contract of the same general format -----------------


def test_new_contract_is_processed_without_code_changes(source_files):
    result = analyze([*source_files, ("new.txt", NEW_CONTRACT.encode())], CHECK_DATE)
    view = _view(result, "STN-104")

    assert view.supplier.value == "АО «Новый Поставщик»"
    assert _values(view) == (
        (ValueState.VALUE, Decimal("2500000")),
        (ValueState.VALUE, date(2026, 3, 25)),
    )
    matching, _ = contracts_with_delivery_before(result, date(2026, 4, 1))
    assert [v.number for v in matching] == ["STN-102", "STN-104"]


def test_new_contract_with_its_amendment(source_files):
    files = [*source_files, ("a.txt", NEW_AMENDMENT.encode()), ("b.txt", NEW_CONTRACT.encode())]

    view = _view(analyze(files, CHECK_DATE), "STN-104")

    assert view.change_docs[0].status == ChangeStatus.APPLIED
    assert view.terms["delivery_date"].effective.value == date(2026, 3, 31)
    assert view.terms["total_cost"].effective.value == Decimal("2500000")


@pytest.mark.parametrize(
    ("check_date", "delivery"),
    [(date(2026, 3, 5), date(2026, 3, 25)), (date(2026, 3, 6), date(2026, 3, 31))],
)
def test_new_amendment_applies_from_its_signing_date(source_files, check_date, delivery):
    files = [*source_files, ("a.txt", NEW_AMENDMENT.encode()), ("b.txt", NEW_CONTRACT.encode())]

    view = _view(analyze(files, check_date), "STN-104")

    assert view.terms["delivery_date"].effective.value == delivery
