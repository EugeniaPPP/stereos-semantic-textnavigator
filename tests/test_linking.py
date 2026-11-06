from tests.builders import (
    amendment_text,
    analyze_texts,
    contract_text,
    letter_text,
    resolve_texts,
)
from textnav.linking import link
from textnav.model import AttentionReason, ChangeStatus


def test_documents_are_grouped_by_contract_number():
    groups, attention = link(
        analyze_texts(
            contract_text("A-1"),
            contract_text("B-2"),
            amendment_text(contract="B-2"),
            letter_text("A-1"),
        )
    )

    assert attention == []
    assert [(g.number, len(g.contracts), len(g.changes)) for g in groups] == [
        ("A-1", 1, 1),
        ("B-2", 1, 1),
    ]


def test_groups_are_sorted_by_natural_number_order():
    groups, _ = link(analyze_texts(contract_text("STN-110"), contract_text("STN-12")))

    assert [g.number for g in groups] == ["STN-12", "STN-110"]


def test_amendment_without_contract_is_orphan_but_processed():
    views, attention = resolve_texts(amendment_text(contract="Z-9"))

    assert views == []
    assert [item.reason for item in attention] == [AttentionReason.ORPHAN]
    assert attention[0].change.status == ChangeStatus.APPLIED
    assert "Z-9" in attention[0].message


def test_orphan_is_linked_once_the_contract_is_uploaded():
    views, attention = resolve_texts(amendment_text(contract="Z-9"), contract_text("Z-9"))

    assert attention == []
    assert [v.number for v in views] == ["Z-9"]
    assert views[0].change_docs[0].status == ChangeStatus.APPLIED


def test_unknown_document_type_needs_attention():
    _, attention = resolve_texts("АКТ ПРИЕМКИ № 5\nК договору A-1.", contract_text())

    assert [item.reason for item in attention] == [AttentionReason.UNKNOWN_TYPE]


def test_document_without_contract_number_is_unlinked():
    _, attention = resolve_texts("ПИСЬМО\nПросим ускорить поставку.")

    assert [item.reason for item in attention] == [AttentionReason.UNLINKED]


def test_document_referring_to_several_contracts_is_unlinked():
    text = "ПИСЬМО\nТема: договор A-1\nПросим учесть также договор B-2."

    _, attention = resolve_texts(text, contract_text("A-1"), contract_text("B-2"))

    assert [item.reason for item in attention] == [AttentionReason.UNLINKED]


def test_identical_upload_is_a_duplicate_and_counted_once():
    groups, attention = link(analyze_texts(contract_text(), contract_text()))

    assert len(groups[0].contracts) == 1
    assert [item.reason for item in attention] == [AttentionReason.DUPLICATE]


def test_linking_does_not_depend_on_input_order():
    texts = [contract_text(), amendment_text(), letter_text(), contract_text("B-2")]

    first = link(analyze_texts(*texts))[0]
    second = link(analyze_texts(*reversed(texts)))[0]

    def shape(groups):
        return [
            (g.number, [c.source.doc_id for c in g.contracts], [c.source.doc_id for c in g.changes])
            for g in groups
        ]

    assert shape(first) == shape(second)
