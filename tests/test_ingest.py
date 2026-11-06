import unicodedata

import pytest

from textnav import ingest
from textnav.ingest import read_document, read_documents
from textnav.model import ReadFailure, SourceDocument


def _read(content: str | bytes, filename: str = "doc.txt") -> SourceDocument:
    data = content.encode("utf-8") if isinstance(content, str) else content
    result = read_document(filename, data)
    assert isinstance(result, SourceDocument), result
    return result


def _sentences(doc: SourceDocument, paragraph_index: int = 0) -> list[str]:
    paragraph = doc.paragraphs[paragraph_index]
    return [doc.text[s.start : s.end] for s in paragraph.sentences]


def _squash(value: str) -> str:
    return "".join(value.split())


# --- sample documents -------------------------------------------------------


def test_all_sample_documents_are_read(source_files):
    documents, failures = read_documents(source_files)

    assert failures == []
    assert [d.filename for d in documents] == [name for name, _ in source_files]


def test_paragraphs_are_the_non_empty_lines(source_files):
    for filename, data in source_files:
        doc = _read(data, filename)
        expected = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]

        assert [p.text for p in doc.paragraphs] == expected, filename


def test_paragraph_and_sentence_offsets_are_exact(source_files):
    for filename, data in source_files:
        doc = _read(data, filename)
        for index, paragraph in enumerate(doc.paragraphs):
            assert paragraph.index == index
            assert doc.text[paragraph.start : paragraph.end] == paragraph.text

            previous_end = paragraph.start
            for span in paragraph.sentences:
                sentence = doc.text[span.start : span.end]
                assert paragraph.start <= span.start < span.end <= paragraph.end
                assert span.start >= previous_end
                assert sentence == sentence.strip()
                previous_end = span.end


def test_sentences_cover_the_paragraph_body(source_files):
    for filename, data in source_files:
        doc = _read(data, filename)
        for paragraph in doc.paragraphs:
            whole = _squash(paragraph.text)
            covered = _squash("".join(doc.text[s.start : s.end] for s in paragraph.sentences))
            prefix = whole[: len(whole) - len(covered)]

            assert whole.endswith(covered), (filename, paragraph.text)
            assert prefix.rstrip(".") == (paragraph.clause or ""), (filename, paragraph.text)


# --- clause numbers ---------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "clause"),
    [
        ("2.1. Общая стоимость поставки составляет 100 рублей.", "2.1"),
        ("1. Пункт 2.1 договора изложить в следующей редакции.", "1"),
        ("3.2.1 Подпункт без точки после номера.", "3.2.1"),
        ("Дата: 05.02.2026", None),
        ("05.02.2026 подписан договор.", None),
        ("100 рублей перечислено.", None),
        ("ДОГОВОР ПОСТАВКИ № 7", None),
    ],
)
def test_clause_number_is_parsed_from_line_start(line, clause):
    assert _read(line).paragraphs[0].clause == clause


# --- sentences --------------------------------------------------------------


def test_sentences_do_not_split_dates_or_clause_references():
    doc = _read(
        "3.2. Поставка не позднее 15.04.2026 по пункту 3.1 и п. 2.1 договора. "
        "Дата приемки может отличаться."
    )

    assert _sentences(doc) == [
        "Поставка не позднее 15.04.2026 по пункту 3.1 и п. 2.1 договора.",
        "Дата приемки может отличаться.",
    ]


def test_sentences_split_after_closing_quote():
    doc = _read("1.1. Покупатель: ООО «СеверМет». Поставщик: ООО «Вектор Прибор».")

    assert _sentences(doc) == ["Покупатель: ООО «СеверМет».", "Поставщик: ООО «Вектор Прибор»."]


def test_sentences_split_inside_quoted_wording():
    doc = _read(
        "1. Пункт 2.1 изложить в редакции: «Стоимость составляет 10 рублей, включая НДС. "
        "Сумма итоговая»."
    )

    assert _sentences(doc) == [
        "Пункт 2.1 изложить в редакции: «Стоимость составляет 10 рублей, включая НДС.",
        "Сумма итоговая».",
    ]


def test_sentence_keeps_closing_quote_after_period():
    doc = _read("Текст «в кавычках.» Следующее предложение.")

    assert _sentences(doc) == ["Текст «в кавычках.»", "Следующее предложение."]


def test_line_without_terminal_punctuation_is_one_sentence():
    assert _sentences(_read("ДОГОВОР ПОСТАВКИ № 7")) == ["ДОГОВОР ПОСТАВКИ № 7"]


# --- decoding and normalization ---------------------------------------------


def test_utf8_bom_is_removed():
    doc = _read("\ufeffДОГОВОР".encode())

    assert doc.text == "ДОГОВОР"
    assert doc.encoding == "utf-8"


def test_windows_line_endings_are_normalized():
    doc = _read("Строка один.\r\n\r\nСтрока два.\r\n".encode())

    assert "\r" not in doc.text
    assert [p.text for p in doc.paragraphs] == ["Строка один.", "Строка два."]


def test_line_endings_do_not_change_document_identity():
    assert _read("А.\r\nБ.".encode()).doc_id == _read("А.\nБ.".encode()).doc_id


def test_cp1251_is_decoded():
    doc = _read("Договор поставки".encode("cp1251"))

    assert doc.text == "Договор поставки"
    assert doc.encoding == "cp1251"


def test_utf16_with_bom_is_decoded():
    doc = _read("Договор поставки".encode("utf-16"))

    assert doc.text == "Договор поставки"
    assert doc.encoding == "utf-16"


def test_text_is_nfc_normalized():
    decomposed = unicodedata.normalize("NFD", "Срок поставки: май")

    assert _read(decomposed).text == unicodedata.normalize("NFC", decomposed)


# --- identity ---------------------------------------------------------------


def test_document_identity_ignores_filename():
    first, second = _read("Текст.", "a.txt"), _read("Текст.", "b.txt")

    assert first.doc_id == second.doc_id
    assert (first.filename, second.filename) == ("a.txt", "b.txt")


def test_document_identity_depends_on_content():
    assert _read("Текст.").doc_id != _read("Текст!").doc_id


# --- failures ---------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"   \n\t\r\n"])
def test_empty_file_is_reported(data):
    result = read_document("empty.txt", data)

    assert isinstance(result, ReadFailure)
    assert result.filename == "empty.txt"
    assert "пуст" in result.reason


@pytest.mark.parametrize("data", [b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", b"\x01\x02\x03data"])
def test_binary_file_is_reported(data):
    result = read_document("image.png", data)

    assert isinstance(result, ReadFailure)
    assert "текстов" in result.reason


def test_undecodable_file_is_reported():
    result = read_document("bad.txt", b"\xd0\x98\x98\x98 abc")

    assert isinstance(result, ReadFailure)
    assert "кодировк" in result.reason


def test_one_unreadable_file_does_not_block_the_others():
    documents, failures = read_documents(
        [("a.txt", "Первый.".encode()), ("b.bin", b"\x00\x01"), ("c.txt", "Третий.".encode())]
    )

    assert [d.filename for d in documents] == ["a.txt", "c.txt"]
    assert [f.filename for f in failures] == ["b.bin"]


def test_unexpected_error_in_one_file_does_not_block_the_others(monkeypatch):
    original = ingest.read_document

    def flaky(filename: str, data: bytes):
        if filename == "boom.txt":
            raise RuntimeError("unexpected")
        return original(filename, data)

    monkeypatch.setattr(ingest, "read_document", flaky)
    documents, failures = read_documents([("boom.txt", b"x"), ("ok.txt", "Текст.".encode())])

    assert [d.filename for d in documents] == ["ok.txt"]
    assert [(f.filename, "Внутренняя ошибка" in f.reason) for f in failures] == [("boom.txt", True)]
