from datetime import date

import pytest

from tests.builders import make_doc
from textnav.ingest import read_document
from textnav.meta import extract_meta
from textnav.model import DocType, DocumentMeta, Extraction, SourceDocument
from textnav.model import ExtractionState as State
from textnav.model import SignatureStatus as Sig

SAMPLES = {
    "01_contract.txt": {
        "doc_type": DocType.CONTRACT,
        "number": "STN-101",
        "contract_number": "STN-101",
        "supplier": "ООО «Вектор Прибор»",
        "doc_date": date(2026, 2, 5),
        "signature": (Sig.SIGNED_BOTH, date(2026, 2, 5)),
        "effective_date": None,
    },
    "02_amendment_signed.txt": {
        "doc_type": DocType.AMENDMENT,
        "number": "1",
        "contract_number": "STN-101",
        "supplier": "ООО «Вектор Прибор»",
        "doc_date": date(2026, 3, 1),
        "signature": (Sig.SIGNED_BOTH, date(2026, 3, 1)),
        "effective_date": date(2026, 3, 1),
    },
    "03_contract.txt": {
        "doc_type": DocType.CONTRACT,
        "number": "STN-102",
        "contract_number": "STN-102",
        "supplier": "ООО «Контур Электро»",
        "doc_date": date(2026, 2, 10),
        "signature": (Sig.SIGNED_BOTH, date(2026, 2, 10)),
        "effective_date": None,
    },
    "04_contract.txt": {
        "doc_type": DocType.CONTRACT,
        "number": "STN-103",
        "contract_number": "STN-103",
        "supplier": "ООО «ПромСнаб Сервис»",
        "doc_date": date(2026, 2, 20),
        "signature": (Sig.SIGNED_BOTH, date(2026, 2, 20)),
        "effective_date": None,
    },
    "05_supplier_email.txt": {
        "doc_type": DocType.LETTER,
        "number": None,
        "contract_number": "STN-102",
        "supplier": None,
        "doc_date": date(2026, 3, 5),
        "signature": (Sig.UNKNOWN, None),
        "effective_date": None,
    },
    "06_amendment_draft.txt": {
        "doc_type": DocType.AMENDMENT_DRAFT,
        "number": "2",
        "contract_number": "STN-101",
        "supplier": "ООО «Вектор Прибор»",
        "doc_date": date(2026, 3, 6),
        "signature": (Sig.NOT_SIGNED, None),
        "effective_date": None,
    },
}

EXTRACTION_FIELDS = ("number", "contract_number", "supplier", "doc_date", "effective_date")


def _meta(text: str) -> DocumentMeta:
    return extract_meta(make_doc(text))


def _assert_citations_exact(doc: SourceDocument, meta: DocumentMeta) -> None:
    extractions: list[Extraction] = [getattr(meta, name) for name in EXTRACTION_FIELDS]
    citations = [c for e in extractions for c in e.citations] + list(meta.signature.citations)
    for citation in citations:
        assert citation.doc_id == doc.doc_id
        assert citation.filename == doc.filename
        assert doc.text[citation.start : citation.end] == citation.quote
        paragraph = doc.paragraphs[citation.paragraph]
        assert paragraph.start <= citation.start < citation.end <= paragraph.end
        if citation.value_start is not None:
            assert citation.start <= citation.value_start < citation.value_end <= citation.end


# --- sample documents -------------------------------------------------------


@pytest.mark.parametrize("filename", sorted(SAMPLES))
def test_sample_document_metadata(filename, source_files):
    doc = read_document(filename, dict(source_files)[filename])
    meta = extract_meta(doc)
    expected = SAMPLES[filename]

    assert meta.doc_type == expected["doc_type"]
    for name in EXTRACTION_FIELDS:
        extraction = getattr(meta, name)
        assert extraction.value == expected[name], name
        assert extraction.state == (State.FOUND if expected[name] else State.NOT_FOUND), name
    assert (meta.signature.status, meta.signature.date) == expected["signature"]
    _assert_citations_exact(doc, meta)


def test_sample_values_are_highlighted_exactly(source_files):
    doc = read_document("02_amendment_signed.txt", dict(source_files)["02_amendment_signed.txt"])
    meta = extract_meta(doc)
    citation = meta.effective_date.citations[0]

    assert citation.quote == "Настоящее соглашение вступает в силу 01.03.2026."
    assert doc.text[citation.value_start : citation.value_end] == "01.03.2026"


# --- document type ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "doc_type"),
    [
        ("Договор поставки № A-1\nТекст.", DocType.CONTRACT),
        ("ДОП. СОГЛАШЕНИЕ № 3 К ДОГОВОРУ A-1\nТекст.", DocType.AMENDMENT),
        ("Проект дополнительного соглашения № 4 к договору A-1\nТекст.", DocType.AMENDMENT_DRAFT),
        ("ПИСЬМО ПОКУПАТЕЛЯ\nТекст.", DocType.LETTER),
        ("УВЕДОМЛЕНИЕ\nОт: ООО «А»\nКому: ООО «Б»\nТема: договор A-1", DocType.LETTER),
        ("ПРОЕКТ ДОГОВОРА\nТекст.", DocType.UNKNOWN),
        ("АКТ ПРИЕМКИ № 5\nТекст.", DocType.UNKNOWN),
    ],
)
def test_document_type_is_classified_by_title(text, doc_type):
    assert _meta(text).doc_type == doc_type


# --- numbers and links ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "number"),
    [
        ("ДОГОВОР ПОСТАВКИ № STN-104", "STN-104"),
        ("ДОГОВОР ПОСТАВКИ N A-7", "A-7"),
        ("ДОГОВОР ПОСТАВКИ № stn–105", "STN-105"),
        ("ДОГОВОР № 15/2026", "15/2026"),
    ],
)
def test_contract_number_is_taken_from_title(title, number):
    meta = _meta(f"{title}\nТекст.")

    assert (meta.number.value, meta.contract_number.value) == (number, number)


def test_contract_without_number_has_no_contract_number():
    meta = _meta("ДОГОВОР ПОСТАВКИ\nТекст.")

    assert meta.contract_number.state == State.NOT_FOUND


@pytest.mark.parametrize(
    ("text", "contract_number"),
    [
        ("ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 3\nК договору поставки № 15 от 01.02.2026.", "15"),
        ("ПИСЬМО\nТема: договор A-1\nПо договору A-1 просим ускорить.", "A-1"),
    ],
)
def test_contract_reference_is_found_in_body(text, contract_number):
    assert _meta(text).contract_number.value == contract_number


def test_several_different_references_are_ambiguous():
    meta = _meta("ПИСЬМО\nТема: договор A-1\nПросим учесть также договор B-2.")

    assert meta.contract_number.state == State.AMBIGUOUS
    assert meta.contract_number.value is None
    assert len(meta.contract_number.citations) == 2


def test_bare_word_or_year_after_contract_is_not_a_reference():
    meta = _meta("ПИСЬМО\nПо условиям договора 2026 года и договора поставки просим ответить.")

    assert meta.contract_number.state == State.NOT_FOUND


# --- supplier and date ------------------------------------------------------


def test_supplier_with_dash():
    assert _meta("ДОГОВОР № A-1\nПоставщик — АО «Ромашка».").supplier.value == "АО «Ромашка»"


def test_supplier_obligation_sentence_is_not_a_supplier():
    meta = _meta("ДОГОВОР № A-1\nПоставщик обязуется поставить товар.")

    assert meta.supplier.state == State.NOT_FOUND


def test_different_suppliers_are_ambiguous():
    meta = _meta("ДОГОВОР № A-1\nПоставщик: ООО «А».\nПоставщик: ООО «Б».")

    assert meta.supplier.state == State.AMBIGUOUS


def test_document_date_with_qualifier():
    assert _meta("ПРОЕКТ\nДата проекта: 06.03.2026").doc_date.value == date(2026, 3, 6)


def test_invalid_document_date_is_not_found():
    assert _meta("ДОГОВОР № A-1\nДата: 31.02.2026").doc_date.state == State.NOT_FOUND


# --- signature --------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_line", "status", "signed_on"),
    [
        ("Статус: подписан обеими сторонами 05.02.2026.", Sig.SIGNED_BOTH, date(2026, 2, 5)),
        ("Статус: подписано сторонами 01.03.2026.", Sig.SIGNED_BOTH, date(2026, 3, 1)),
        (
            "Статус подписания: подписан обеими сторонами «5» февраля 2026 г.",
            Sig.SIGNED_BOTH,
            date(2026, 2, 5),
        ),
        ("Статус: подписано только поставщиком 01.03.2026.", Sig.SIGNED_PARTIAL, date(2026, 3, 1)),
        ("Статус: подписан поставщиком, покупателем не подписан.", Sig.SIGNED_PARTIAL, None),
        ("Статус: подписан одной из сторон 02.03.2026.", Sig.SIGNED_PARTIAL, date(2026, 3, 2)),
        ("Статус: проект на согласовании, не подписан ни одной стороной.", Sig.NOT_SIGNED, None),
        ("Статус: не подписан обеими сторонами.", Sig.NOT_SIGNED, None),
        ("Статус: на подписании.", Sig.NOT_SIGNED, None),
        ("Статус: согласован.", Sig.UNKNOWN, None),
        ("Статус: подписан обеими сторонами 05.02.2026 и 07.02.2026.", Sig.SIGNED_BOTH, None),
    ],
)
def test_signature_status_from_status_line(status_line, status, signed_on):
    signature = _meta(f"ДОГОВОР № A-1\n{status_line}").signature

    assert (signature.status, signature.date) == (status, signed_on)
    assert signature.citations


def test_contradicting_status_lines_are_unknown():
    text = "ДОГОВОР № A-1\nСтатус: подписан обеими сторонами 05.02.2026.\nСтатус: не подписан."

    assert _meta(text).signature.status == Sig.UNKNOWN


def test_signature_is_unknown_without_status_line():
    text = "ДОГОВОР № A-1\nДоговор подписан обеими сторонами 05.02.2026."

    assert _meta(text).signature.status == Sig.UNKNOWN


# --- effective date ---------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Настоящее соглашение вступает в силу 01.03.2026.", date(2026, 3, 1)),
        ("Договор вступает в силу с 15.02.2026.", date(2026, 2, 15)),
        ("Изменения действуют с 10.03.2026.", date(2026, 3, 10)),
        ("Соглашение вступает в силу «1» марта 2026 г.", date(2026, 3, 1)),
        ("Договор вступает в силу с момента подписания.", None),
        ("Изменения вступят в силу только после подписания сторонами.", None),
        ("Изменения действуют после наступления даты вступления в силу.", None),
    ],
)
def test_effective_date(sentence, expected):
    assert _meta(f"ДОГОВОР № A-1\n5.1. {sentence}").effective_date.value == expected


def test_different_effective_dates_are_ambiguous():
    text = (
        "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ A-1\n"
        "Изменения вступают в силу 01.03.2026. Соглашение вступает в силу 02.03.2026."
    )

    assert _meta(text).effective_date.state == State.AMBIGUOUS
