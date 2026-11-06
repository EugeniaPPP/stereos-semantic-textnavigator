from datetime import date
from decimal import Decimal

import pytest

from tests.builders import (
    amendment_text,
    contract_text,
    cost_change,
    delivery_change,
    draft_text,
    letter_text,
    resolve_one,
)
from textnav.model import AlertCode, ChangeStatus, ContractStatus, ContractView, ValueState

ONE_MILLION = Decimal("1000000")


def _cost(view: ContractView):
    return view.terms["total_cost"].effective


def _delivery(view: ContractView):
    return view.terms["delivery_date"].effective


def _codes(view: ContractView) -> list[AlertCode]:
    return [alert.code for alert in view.alerts]


def _change_statuses(view: ContractView) -> list[ChangeStatus]:
    return [change.status for change in view.change_docs]


# --- contract status --------------------------------------------------------


def test_signed_contract_is_in_force_with_its_values():
    view = resolve_one(contract_text())

    assert view.status == ContractStatus.IN_FORCE
    assert (_cost(view).state, _cost(view).value) == (ValueState.VALUE, ONE_MILLION)
    assert _delivery(view).value == date(2026, 4, 30)
    assert _cost(view).source_doc_id == view.contracts[0].source.doc_id
    assert view.alerts == ()


def test_contract_signed_after_check_date_is_not_in_force():
    view = resolve_one(contract_text(status="подписан обеими сторонами 15.03.2026"))

    assert view.status == ContractStatus.NOT_IN_FORCE
    assert "после даты проверки" in view.status_reason
    assert AlertCode.CONTRACT_NOT_IN_FORCE in _codes(view)


@pytest.mark.parametrize(
    ("check_date", "status"),
    [
        (date(2026, 3, 19), ContractStatus.NOT_IN_FORCE),
        (date(2026, 3, 20), ContractStatus.IN_FORCE),
    ],
)
def test_explicit_contract_effective_date_is_respected(check_date, status):
    text = contract_text(extra=("9.1. Договор вступает в силу 20.03.2026.",))

    view = resolve_one(text, check_date=check_date)

    assert view.status == status
    if status is ContractStatus.NOT_IN_FORCE:
        assert "вступает в силу 20.03.2026" in view.status_reason


def test_contract_signed_by_one_party_is_not_in_force():
    view = resolve_one(contract_text(status="подписан только поставщиком 01.02.2026"))

    assert view.status == ContractStatus.NOT_IN_FORCE


@pytest.mark.parametrize(
    "status",
    [
        "не подписан",  # a contract-typed document that says it is not signed: contradiction
        "проект на согласовании",
        None,  # no status line at all
        "подписан обеими сторонами",  # no signing date
    ],
)
def test_unreliable_contract_status_needs_review(status):
    view = resolve_one(contract_text(status=status))

    assert view.status == ContractStatus.NEEDS_REVIEW
    assert AlertCode.CONTRACT_NEEDS_REVIEW in _codes(view)


def test_two_different_contracts_with_the_same_number_need_review():
    view = resolve_one(
        contract_text(), contract_text(cost="2.1. Общая стоимость составляет 5 рублей.")
    )

    assert view.status == ContractStatus.NEEDS_REVIEW
    assert len(view.contracts) == 2
    assert _cost(view).state == ValueState.NEEDS_REVIEW


# --- original values --------------------------------------------------------


def test_cost_stated_absent_is_no_data_with_citation():
    view = resolve_one(
        contract_text(cost="2.1. Числовое значение стоимости в договоре не указано.")
    )

    assert _cost(view).state == ValueState.NO_DATA
    assert _cost(view).citations


def test_ambiguous_contract_cost_needs_review():
    view = resolve_one(contract_text(extra=("9.2. Цена договора составляет 2 000 000 рублей.",)))

    assert _cost(view).state == ValueState.NEEDS_REVIEW
    assert AlertCode.FIELD_NEEDS_REVIEW in _codes(view)


# --- change status matrix ---------------------------------------------------


def test_applied_amendment_updates_only_the_changed_field():
    view = resolve_one(contract_text(), amendment_text())
    amendment_id = view.change_docs[0].analysis.source.doc_id

    assert _change_statuses(view) == [ChangeStatus.APPLIED]
    assert (_cost(view).value, _cost(view).source_doc_id) == (Decimal("1100000"), amendment_id)
    assert view.terms["total_cost"].original.value == ONE_MILLION
    assert view.terms["total_cost"].changed_by == (amendment_id,)
    assert _delivery(view).source_doc_id == view.contracts[0].source.doc_id
    assert view.alerts == ()


def test_signed_amendment_not_yet_effective_is_pending_not_a_proposal():
    text = amendment_text(effective="Настоящее соглашение вступает в силу 15.03.2026.")

    view = resolve_one(contract_text(), text)

    assert _change_statuses(view) == [ChangeStatus.NOT_YET_EFFECTIVE]
    assert "вступает в силу 15.03.2026" in view.change_docs[0].reason
    assert _cost(view).value == ONE_MILLION
    assert _codes(view) == [AlertCode.CHANGE_PENDING]
    assert view.alerts[0].field == "total_cost"


def test_amendment_signed_after_check_date_is_pending():
    text = amendment_text(
        status="подписано обеими сторонами 12.03.2026",
        effective="Настоящее соглашение вступает в силу 12.03.2026.",
    )

    view = resolve_one(contract_text(), text)

    assert _change_statuses(view) == [ChangeStatus.NOT_YET_EFFECTIVE]
    assert "после даты проверки" in view.change_docs[0].reason
    assert _cost(view).value == ONE_MILLION


def test_amendment_applies_from_check_date_inclusive():
    text = amendment_text(effective="Настоящее соглашение вступает в силу 10.03.2026.")

    assert _change_statuses(resolve_one(contract_text(), text)) == [ChangeStatus.APPLIED]


def test_amendment_effective_on_signing_uses_the_signing_date():
    text = amendment_text(effective="Настоящее соглашение вступает в силу с момента подписания.")

    view = resolve_one(contract_text(), text)

    assert _change_statuses(view) == [ChangeStatus.APPLIED]
    assert _cost(view).value == Decimal("1100000")


def test_amendment_without_effective_date_needs_review_and_blocks_the_field():
    view = resolve_one(contract_text(), amendment_text(effective=None))

    assert _change_statuses(view) == [ChangeStatus.NEEDS_REVIEW]
    assert _cost(view).state == ValueState.NEEDS_REVIEW
    assert view.terms["total_cost"].applied.value == ONE_MILLION  # last confirmed value
    assert _delivery(view).state == ValueState.VALUE
    assert AlertCode.CHANGE_NEEDS_REVIEW in _codes(view)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("подписано только поставщиком 01.03.2026", ChangeStatus.PROPOSAL),
        ("не подписано", ChangeStatus.NEEDS_REVIEW),  # final title + "not signed": contradiction
        ("проект", ChangeStatus.NEEDS_REVIEW),
        (None, ChangeStatus.NEEDS_REVIEW),
        ("подписано обеими сторонами", ChangeStatus.NEEDS_REVIEW),  # no signing date
    ],
)
def test_amendment_signature_matrix(status, expected):
    view = resolve_one(contract_text(), amendment_text(status=status))

    assert _change_statuses(view) == [expected]
    expected_cost = (
        ValueState.VALUE if expected is ChangeStatus.PROPOSAL else ValueState.NEEDS_REVIEW
    )
    assert _cost(view).state == expected_cost


def test_unsigned_draft_is_a_proposal_and_changes_nothing():
    view = resolve_one(contract_text(), draft_text())

    assert _change_statuses(view) == [ChangeStatus.PROPOSAL]
    assert _delivery(view).value == date(2026, 4, 30)
    assert [(a.code, a.field) for a in view.alerts] == [
        (AlertCode.CHANGE_PROPOSAL, "delivery_date")
    ]
    assert "10.05.2026" in view.alerts[0].message


def test_draft_marked_signed_by_both_needs_review():
    view = resolve_one(contract_text(), draft_text(status="подписан обеими сторонами 07.03.2026"))

    assert _change_statuses(view) == [ChangeStatus.NEEDS_REVIEW]
    assert _delivery(view).state == ValueState.NEEDS_REVIEW


def test_letter_is_a_proposal():
    view = resolve_one(contract_text(), letter_text())

    assert _change_statuses(view) == [ChangeStatus.PROPOSAL]
    assert _delivery(view).value == date(2026, 4, 30)
    assert view.alerts[0].code == AlertCode.CHANGE_PROPOSAL
    assert "15.05.2026" in view.alerts[0].message


def test_proposal_dated_after_check_date_has_no_alert_but_is_listed():
    view = resolve_one(contract_text(), letter_text(doc_date="12.03.2026"))

    assert _change_statuses(view) == [ChangeStatus.PROPOSAL]
    assert view.alerts == ()


def test_needs_review_document_dated_after_check_date_does_not_block_the_field():
    view = resolve_one(contract_text(), amendment_text(effective=None, doc_date="12.03.2026"))

    assert _cost(view).state == ValueState.VALUE


# --- field rules ------------------------------------------------------------


def test_unparsed_change_in_applied_amendment_needs_review():
    text = amendment_text(changes=("Увеличить общую стоимость на 100 000 рублей.",))

    view = resolve_one(contract_text(), text)

    assert _cost(view).state == ValueState.NEEDS_REVIEW
    assert view.terms["total_cost"].original.value == ONE_MILLION
    assert AlertCode.FIELD_NEEDS_REVIEW in _codes(view)


def test_rewritten_contract_clause_without_recognizable_value_needs_review():
    text = amendment_text(
        changes=(
            "Пункт 2.1 договора изложить в следующей редакции: "
            "«Порядок расчетов определяется спецификацией».",
        )
    )

    view = resolve_one(contract_text(), text)

    assert _cost(view).state == ValueState.NEEDS_REVIEW
    assert _delivery(view).state == ValueState.VALUE


def test_later_amendment_with_clear_value_overrides_needs_review():
    first = amendment_text(changes=("Увеличить общую стоимость на 100 000 рублей.",))
    second = amendment_text(
        number="2",
        status="подписано обеими сторонами 05.03.2026",
        changes=(cost_change("1 200 000 рублей"),),
        effective="Настоящее соглашение вступает в силу 05.03.2026.",
        doc_date="05.03.2026",
    )

    view = resolve_one(contract_text(), second, first)

    assert (_cost(view).state, _cost(view).value) == (ValueState.VALUE, Decimal("1200000"))
    assert len(view.terms["total_cost"].changed_by) == 2


def test_amendments_apply_in_order_of_effective_date_not_number():
    later = amendment_text(
        number="1",
        status="подписано обеими сторонами 01.03.2026",
        changes=(cost_change("900 000 рублей"),),
        effective="Настоящее соглашение вступает в силу 05.03.2026.",
    )
    earlier = amendment_text(
        number="2",
        status="подписано обеими сторонами 01.03.2026",
        changes=(cost_change("800 000 рублей"),),
        effective="Настоящее соглашение вступает в силу 02.03.2026.",
    )

    assert _cost(resolve_one(contract_text(), later, earlier)).value == Decimal("900000")
    assert _cost(resolve_one(contract_text(), earlier, later)).value == Decimal("900000")


def test_same_effective_date_with_different_values_needs_review():
    first = amendment_text(changes=(delivery_change("15.05.2026"),))
    second = amendment_text(number="2", changes=(delivery_change("20.05.2026"),))

    view = resolve_one(contract_text(), first, second)

    assert _delivery(view).state == ValueState.NEEDS_REVIEW
    assert "одной датой вступления" in _delivery(view).reason


def test_same_effective_date_with_the_same_value_is_fine():
    first = amendment_text(changes=(delivery_change("15.05.2026"),))
    second = amendment_text(number="2", changes=(delivery_change("15.05.2026"),))

    assert _delivery(resolve_one(contract_text(), first, second)).value == date(2026, 5, 15)


def test_unrecognized_change_of_unknown_clause_is_reported():
    text = amendment_text(
        changes=("Пункт 4.1 договора изложить в следующей редакции: «Неустойка составляет 0,2%».",)
    )

    view = resolve_one(contract_text(), text)

    assert _cost(view).value == ONE_MILLION
    assert _codes(view) == [AlertCode.UNRECOGNIZED_CHANGE]


def test_applied_amendment_without_change_clauses_is_reported():
    text = amendment_text(changes=("Стороны подтверждают действие договора.",))

    assert AlertCode.EMPTY_AMENDMENT in _codes(resolve_one(contract_text(), text))


def test_supplier_mismatch_is_reported():
    view = resolve_one(contract_text(), amendment_text(supplier="ООО «Другой»"))

    assert AlertCode.SUPPLIER_MISMATCH in _codes(view)


def test_contract_not_in_force_still_computes_values_for_details():
    view = resolve_one(contract_text(status="подписан обеими сторонами 15.03.2026"))

    assert view.status == ContractStatus.NOT_IN_FORCE
    assert view.terms["total_cost"].applied.value == ONE_MILLION


def test_terms_of_a_contract_not_in_force_are_not_shown_as_effective():
    view = resolve_one(contract_text(status="подписан обеими сторонами 15.03.2026"))

    assert _cost(view).state == ValueState.NOT_IN_FORCE
    assert _delivery(view).state == ValueState.NOT_IN_FORCE
    assert "после даты проверки" in _cost(view).reason
    assert _codes(view) == [AlertCode.CONTRACT_NOT_IN_FORCE]


def test_terms_of_a_contract_with_unreliable_status_need_review():
    view = resolve_one(contract_text(status=None))

    assert _cost(view).state == ValueState.NEEDS_REVIEW
    assert view.terms["total_cost"].applied.value == ONE_MILLION
    assert _codes(view) == [AlertCode.CONTRACT_NEEDS_REVIEW]
