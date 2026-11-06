from tests.builders import make_doc
from textnav.evidence import cite
from textnav.model import Span
from textnav.ui.viewer import document_html


def _html(text: str, paragraph: int, phrase: str, value: str | None):
    doc = make_doc(text, "<b>file</b>.txt")
    target = doc.paragraphs[paragraph]
    start = doc.text.index(phrase)
    span = Span(start, start + len(phrase))
    if value is None:
        return doc, document_html(doc, cite(doc, target, span))
    value_start = doc.text.index(value, start)
    citation = cite(doc, target, span, value_start, value_start + len(value))
    return doc, document_html(doc, citation)


TEXT = (
    "ДОГОВОР <script>alert(1)</script>\n"
    'Статус: "><img src=x onerror=alert(2)>.\n'
    "2.1. Цена договора составляет 100 рублей. Оплата позже."
)


def test_document_text_is_escaped():
    _, html = _html(TEXT, 2, "Цена договора составляет 100 рублей.", "100 рублей")

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img" not in html
    assert "<b>file</b>" not in html


def test_target_paragraph_quote_and_value_are_marked():
    _, html = _html(TEXT, 2, "Цена договора составляет 100 рублей.", "100 рублей")

    assert 'id="target"' in html
    assert '<span class="quote">Цена договора составляет <mark>100 рублей</mark>.</span>' in html
    assert "Оплата позже." in html
    assert html.count('id="target"') == 1


def test_viewer_scrolls_to_the_target():
    _, html = _html(TEXT, 2, "Цена договора составляет 100 рублей.", "100 рублей")

    assert 'getElementById("target").scrollIntoView' in html


def test_citation_without_value_has_no_mark():
    _, html = _html(TEXT, 2, "Цена договора составляет 100 рублей.", None)

    assert "<mark>" not in html
    assert '<span class="quote">Цена договора составляет 100 рублей.</span>' in html


def test_every_paragraph_is_shown():
    doc, html = _html(TEXT, 2, "Цена договора составляет 100 рублей.", "100 рублей")

    assert html.count("<p ") == len(doc.paragraphs)
