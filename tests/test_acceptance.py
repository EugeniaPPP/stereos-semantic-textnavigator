"""PRD §4 acceptance criteria and the four user questions of docs/TASK.md, on documents/."""

from datetime import date
from decimal import Decimal

import pytest

from textnav.model import (
    AlertCode,
    AnalysisResult,
    AttentionReason,
    ChangeStatus,
    ContractStatus,
    ContractView,
    DocumentAnalysis,
    ValueState,
)
from textnav.patterns import parse_date, parse_money
from textnav.pipeline import analyze, contracts_with_delivery_before, unagreed_changes

CHECK_DATE = date(2026, 3, 10)


@pytest.fixture(scope="module")
def result(source_files) -> AnalysisResult:
    return analyze(source_files, CHECK_DATE)


def _view(result: AnalysisResult, number: str) -> ContractView:
    return {v.number: v for v in result.contracts}[number]


def _change(view: ContractView, filename: str):
    return next(c for c in view.change_docs if c.analysis.source.filename == filename)


def _documents(result: AnalysisResult) -> dict[str, DocumentAnalysis]:
    docs = {}
    for view in result.contracts:
        docs |= {a.source.doc_id: a for a in view.contracts}
        docs |= {c.analysis.source.doc_id: c.analysis for c in view.change_docs}
    return docs


# --- PRD §4 table -------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "cost", "delivery"),
    [
        ("STN-101", Decimal("1380000"), date(2026, 4, 30)),
        ("STN-102", Decimal("840000"), date(2026, 3, 20)),
        ("STN-103", None, date(2026, 4, 30)),
    ],
)
def test_prd_acceptance_table(result, number, cost, delivery):
    view = _view(result, number)
    total, term = view.terms["total_cost"].effective, view.terms["delivery_date"].effective

    assert view.status == ContractStatus.IN_FORCE
    assert (total.state, total.value) == (
        (ValueState.VALUE, cost) if cost else (ValueState.NO_DATA, None)
    )
    assert (term.state, term.value) == (ValueState.VALUE, delivery)


def test_exactly_three_contracts_and_nothing_needs_attention(result):
    assert [v.number for v in result.contracts] == ["STN-101", "STN-102", "STN-103"]
    assert result.attention == ()


def test_suppliers(result):
    assert [v.supplier.value for v in result.contracts] == [
        "ООО «Вектор Прибор»",
        "ООО «Контур Электро»",
        "ООО «ПромСнаб Сервис»",
    ]


# --- PRD §4 checks ----------------------------------------------------------------


def test_1_signed_amendment_applies_and_draft_does_not(result):
    view = _view(result, "STN-101")
    amendment = _change(view, "02_amendment_signed.txt")

    assert amendment.status == ChangeStatus.APPLIED
    assert _change(view, "06_amendment_draft.txt").status == ChangeStatus.PROPOSAL
    for field in ("total_cost", "delivery_date"):
        assert view.terms[field].effective.source_doc_id == amendment.analysis.source.doc_id
    assert view.terms["total_cost"].original.value == Decimal("1200000")
    assert view.terms["delivery_date"].original.value == date(2026, 4, 15)


def test_2_letter_is_shown_separately_and_advance_is_not_the_total(result):
    view = _view(result, "STN-102")
    letter = _change(view, "05_supplier_email.txt")
    total = view.terms["total_cost"].effective
    text = view.contracts[0].source.text

    assert letter.status == ChangeStatus.PROPOSAL
    assert [a.field for a in unagreed_changes(view)] == ["delivery_date"]
    assert view.terms["delivery_date"].effective.value == date(2026, 3, 20)
    assert [text[c.value_start : c.value_end] for c in total.citations] == [
        "840 000 (восемьсот сорок тысяч) рублей"
    ]


def test_3_budget_limit_is_not_the_cost(result):
    total = _view(result, "STN-103").terms["total_cost"].effective

    assert total.state == ValueState.NO_DATA
    assert total.citations and not any("600 000" in c.quote for c in total.citations)


def test_4_filter_before_april_returns_stn102_with_proposed_change(result):
    matching, excluded = contracts_with_delivery_before(result, date(2026, 4, 1))

    assert [v.number for v in matching] == ["STN-102"]
    assert excluded == 0
    assert [a.code for a in unagreed_changes(matching[0], "delivery_date")] == [
        AlertCode.CHANGE_PROPOSAL
    ]


BEFORE = (Decimal("1200000"), date(2026, 4, 15))
AFTER = (Decimal("1380000"), date(2026, 4, 30))
STN102 = (Decimal("840000"), date(2026, 3, 20))
STN103 = (None, date(2026, 4, 30))


@pytest.mark.parametrize(
    ("check_date", "expected"),
    [
        (date(2026, 2, 4), {"STN-101": None, "STN-102": None, "STN-103": None}),
        (date(2026, 2, 5), {"STN-101": BEFORE, "STN-102": None, "STN-103": None}),
        (date(2026, 2, 28), {"STN-101": BEFORE, "STN-102": STN102, "STN-103": STN103}),
        (date(2026, 3, 1), {"STN-101": AFTER, "STN-102": STN102, "STN-103": STN103}),
    ],
)
def test_5_check_date_changes_applicability(source_files, check_date, expected):
    result = analyze(source_files, check_date)

    for number, values in expected.items():
        view = _view(result, number)
        if values is None:
            assert view.status == ContractStatus.NOT_IN_FORCE, number
            continue
        total, term = view.terms["total_cost"].effective, view.terms["delivery_date"].effective
        assert view.status == ContractStatus.IN_FORCE, number
        assert (total.value, term.value) == values, number


def test_9_missing_value_is_not_invented(result):
    total = _view(result, "STN-103").terms["total_cost"]

    assert (total.original.state, total.effective.state) == (ValueState.NO_DATA, ValueState.NO_DATA)
    assert total.effective.value is None


def test_10_amendment_without_contract_is_processed_but_not_resolved(source_files):
    files = [f for f in source_files if f[0] == "02_amendment_signed.txt"]

    result = analyze(files, CHECK_DATE)

    assert result.contracts == ()
    assert [item.reason for item in result.attention] == [AttentionReason.ORPHAN]
    assert result.attention[0].change.status == ChangeStatus.APPLIED
    assert "STN-101" in result.attention[0].message


def test_11_every_citation_points_to_its_source_paragraph(result):
    docs = _documents(result)
    checked = 0
    for view in result.contracts:
        values = [v for t in view.terms.values() for v in (t.original, t.applied, t.effective)]
        citations = [c for v in values for c in v.citations]
        citations += [c for a in view.alerts for c in a.citations]
        for citation in citations:
            doc = docs[citation.doc_id]
            paragraph = doc.source.paragraphs[citation.paragraph]
            assert citation.filename == doc.source.filename
            assert doc.source.text[citation.start : citation.end] == citation.quote
            assert paragraph.start <= citation.start < citation.end <= paragraph.end
            checked += 1
    assert checked > 10


def test_11_highlighted_fragment_is_the_value_itself(result):
    docs = _documents(result)
    for view in result.contracts:
        for term in view.terms.values():
            value = term.effective
            if value.state is not ValueState.VALUE:
                continue
            parse = parse_money if isinstance(value.value, Decimal) else parse_date
            for c in value.citations:
                fragment = docs[c.doc_id].source.text[c.value_start : c.value_end]
                assert parse(fragment) == value.value


# --- the four user questions (docs/TASK.md) ---------------------------------------


def test_question_1_delivery_of_stn101_on_march_10(result):
    term = _view(result, "STN-101").terms["delivery_date"].effective

    assert (term.state, term.value) == (ValueState.VALUE, date(2026, 4, 30))


def test_question_2_total_of_stn102(result):
    assert _view(result, "STN-102").terms["total_cost"].effective.value == Decimal("840000")


def test_question_3_total_of_stn103(result):
    assert _view(result, "STN-103").terms["total_cost"].effective.state == ValueState.NO_DATA


def test_question_4_deliveries_before_april_and_unagreed_delivery_changes(result):
    matching, _ = contracts_with_delivery_before(result, date(2026, 4, 1))
    changes = {v.number: unagreed_changes(v, "delivery_date") for v in matching}

    assert list(changes) == ["STN-102"]
    assert len(changes["STN-102"]) == 1
    assert "27.03.2026" in changes["STN-102"][0].message
