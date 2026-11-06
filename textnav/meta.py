"""Document-level metadata: type, numbers, supplier, dates and signature status.

Every value comes with citations. Anything unclear is reported as NOT_FOUND, AMBIGUOUS or
an UNKNOWN signature; applicability decisions are made later by the resolver.
"""

import re
from datetime import date

from textnav.evidence import cite, collect, iter_sentences
from textnav.model import (
    Citation,
    DocType,
    DocumentMeta,
    Extraction,
    Signature,
    SignatureStatus,
    SourceDocument,
    Span,
)
from textnav.patterns import (
    DATE,
    NUMBER,
    NUMBER_SIGN,
    find_dates,
    looks_like_number,
    normalize_number,
    parse_date,
)

_I = re.IGNORECASE

# The title is the first paragraph. Order matters: a draft title also contains "СОГЛАШЕНИЯ".
_TYPE_BY_TITLE = (
    (DocType.AMENDMENT_DRAFT, re.compile(r"ПРОЕКТ\s+(?:ДОПОЛНИТЕЛЬНОГО|ДОП\.)\s*СОГЛАШЕНИЯ", _I)),
    (DocType.AMENDMENT, re.compile(r"(?:ДОПОЛНИТЕЛЬНОЕ|ДОП\.)\s*СОГЛАШЕНИЕ", _I)),
    (DocType.CONTRACT, re.compile(r"ДОГОВОР\b", _I)),
    (DocType.LETTER, re.compile(r"ПИСЬМО\b", _I)),
)
_LETTER_HEADERS = (re.compile(r"От\s*:", _I), re.compile(r"Кому\s*:", _I))

_CONTRACT_OWN_NUMBER = re.compile(
    rf"ДОГОВОР(?:\s+ПОСТАВКИ)?\s*{NUMBER_SIGN}\s*(?P<value>{NUMBER})", _I
)
_AMENDMENT_OWN_NUMBER = re.compile(rf"СОГЛАШЕНИ[ЕЯ]\s*{NUMBER_SIGN}\s*(?P<value>{NUMBER})", _I)
_CONTRACT_REFERENCE = re.compile(
    rf"(?<![А-Яа-яЁё])ДОГОВОР[А-ЯЁ]*(?:\s+ПОСТАВКИ)?"
    rf"(?:\s*{NUMBER_SIGN}\s*(?P<signed>{NUMBER})|\s+(?P<bare>{NUMBER}))",
    _I,
)

_SUPPLIER = re.compile(r"Поставщик\s*[:—–-]\s*(?P<value>\S.*?)\s*\.?$", _I)
_DOC_DATE = re.compile(rf"Дата(?:\s+[а-яё]+)?\s*:\s*(?P<value>{DATE})", _I)

_STATUS_LINE = re.compile(r"Статус(?:\s+[а-яё]+)?\s*:", _I)
_NOT_SIGNED = re.compile(r"\bне\s+подписан|\bпроект\w*|\bна\s+(?:согласовании|подписании)", _I)
_SIGNED_PARTIAL = re.compile(
    r"(?<!не\s)\bподписан[аоы]?\s+(?:только\s+)?(?:одной\s+(?:из\s+)?сторон\w*|поставщиком|покупателем)",
    _I,
)
_SIGNED_BOTH = re.compile(r"(?<!не\s)\bподписан[аоы]?\s+(?:обеими\s+)?сторонами", _I)

# The subject (the document itself or its changes) must precede the verb, so that
# "Цена действует с <дата>" is not mistaken for the effective date of the document.
_EFFECTIVE_DATE = re.compile(
    r"(?:договор|соглашени|изменени)\w*\b.{0,60}?"
    r"(?:вступ\w*\s+в\s+(?:законную\s+)?силу|(?:действу|применя)\w*)"
    rf"\s+(?:с\s+)?(?P<value>{DATE})",
    _I,
)
_EFFECTIVE_ON_SIGNING = re.compile(
    r"(?:договор|соглашени|изменени)\w*\b.{0,60}?вступ\w*\s+в\s+(?:законную\s+)?силу\s+"
    r"(?P<value>с\s+(?:момента|даты|дня)\s+(?:(?:его|ее|её|их)\s+)?подписания)",
    _I,
)


def extract_meta(doc: SourceDocument) -> DocumentMeta:
    doc_type = _classify(doc)
    number = _own_number(doc, doc_type)
    if doc_type is DocType.CONTRACT:
        contract_number = Extraction(
            "contract_number", number.state, number.value, number.citations
        )
    else:
        contract_number = _contract_reference(doc)
    signature = _signature(doc)
    return DocumentMeta(
        doc_type=doc_type,
        number=number,
        contract_number=contract_number,
        supplier=_supplier(doc),
        doc_date=_doc_date(doc),
        signature=signature,
        effective_date=_effective_date(doc, signature),
    )


def _classify(doc: SourceDocument) -> DocType:
    title = doc.paragraphs[0].text
    for doc_type, pattern in _TYPE_BY_TITLE:
        if pattern.match(title):
            return doc_type
    has_letter_headers = all(
        any(header.match(p.text) for p in doc.paragraphs) for header in _LETTER_HEADERS
    )
    return DocType.LETTER if has_letter_headers else DocType.UNKNOWN


def _own_number(doc: SourceDocument, doc_type: DocType) -> Extraction:
    pattern = {
        DocType.CONTRACT: _CONTRACT_OWN_NUMBER,
        DocType.AMENDMENT: _AMENDMENT_OWN_NUMBER,
        DocType.AMENDMENT_DRAFT: _AMENDMENT_OWN_NUMBER,
    }.get(doc_type)
    title = doc.paragraphs[0]
    match = pattern.search(title.text) if pattern else None
    if match is None or not looks_like_number(match.group("value"), after_number_sign=True):
        return collect("number", [])
    offset = title.start
    citation = cite(
        doc,
        title,
        Span(title.start, title.end),
        offset + match.start("value"),
        offset + match.end("value"),
    )
    return collect("number", [(normalize_number(match.group("value")), citation)])


def _contract_reference(doc: SourceDocument) -> Extraction:
    candidates: list[tuple[str, Citation]] = []
    for paragraph, span, sentence in iter_sentences(doc):
        for match in _CONTRACT_REFERENCE.finditer(sentence):
            group = "signed" if match.group("signed") else "bare"
            token = match.group(group)
            if not looks_like_number(token, after_number_sign=group == "signed"):
                continue
            citation = cite(
                doc, paragraph, span, span.start + match.start(group), span.start + match.end(group)
            )
            candidates.append((normalize_number(token), citation))
    return collect("contract_number", candidates)


def _supplier(doc: SourceDocument) -> Extraction:
    candidates: list[tuple[str, Citation]] = []
    for paragraph, span, sentence in iter_sentences(doc):
        if match := _SUPPLIER.match(sentence):
            value = " ".join(match.group("value").split())
            citation = cite(
                doc,
                paragraph,
                span,
                span.start + match.start("value"),
                span.start + match.end("value"),
            )
            candidates.append((value, citation))
    return collect("supplier", candidates)


def _doc_date(doc: SourceDocument) -> Extraction:
    return collect("doc_date", _date_candidates(doc, _DOC_DATE, anchored=True))


def _effective_date(doc: SourceDocument, signature: Signature) -> Extraction:
    """Explicit dates, or the signing date for "вступает в силу с момента подписания"."""
    candidates = _date_candidates(doc, _EFFECTIVE_DATE, anchored=False)
    if signature.date is not None:
        for paragraph, span, sentence in iter_sentences(doc):
            for match in _EFFECTIVE_ON_SIGNING.finditer(sentence):
                citation = cite(
                    doc,
                    paragraph,
                    span,
                    span.start + match.start("value"),
                    span.start + match.end("value"),
                )
                candidates.append((signature.date, citation))
    return collect("effective_date", candidates)


def _date_candidates(
    doc: SourceDocument, pattern: re.Pattern[str], anchored: bool
) -> list[tuple[date, Citation]]:
    candidates = []
    for paragraph, span, sentence in iter_sentences(doc):
        matches = [pattern.match(sentence)] if anchored else pattern.finditer(sentence)
        for match in filter(None, matches):
            value = parse_date(match.group("value"))
            if value is None:
                continue
            citation = cite(
                doc,
                paragraph,
                span,
                span.start + match.start("value"),
                span.start + match.end("value"),
            )
            candidates.append((value, citation))
    return candidates


def _signature(doc: SourceDocument) -> Signature:
    """Signature status comes only from "Статус:" lines; without them it is UNKNOWN."""
    found: set[SignatureStatus] = set()
    dates: list[tuple[object, int, int]] = []
    citations: list[Citation] = []
    for paragraph in doc.paragraphs:
        if not _STATUS_LINE.match(paragraph.text):
            continue
        text = paragraph.text
        if _NOT_SIGNED.search(text):
            found.add(SignatureStatus.NOT_SIGNED)
        if _SIGNED_PARTIAL.search(text):
            found.add(SignatureStatus.SIGNED_PARTIAL)
        if _SIGNED_BOTH.search(text):
            found.add(SignatureStatus.SIGNED_BOTH)
        paragraph_dates = [
            (v, paragraph.start + s, paragraph.start + e) for v, s, e in find_dates(text)
        ]
        dates.extend(paragraph_dates)
        value_span = paragraph_dates[0][1:] if len(paragraph_dates) == 1 else (None, None)
        citations.append(cite(doc, paragraph, Span(paragraph.start, paragraph.end), *value_span))

    status = _combine_statuses(found)
    distinct_dates = {value for value, _, _ in dates}
    signed_on = None
    if (
        status in (SignatureStatus.SIGNED_BOTH, SignatureStatus.SIGNED_PARTIAL)
        and len(distinct_dates) == 1
    ):
        signed_on = next(iter(distinct_dates))
    return Signature(status, signed_on, tuple(citations))


def _combine_statuses(found: set[SignatureStatus]) -> SignatureStatus:
    signed_both = SignatureStatus.SIGNED_BOTH in found
    if signed_both and len(found) > 1:
        return SignatureStatus.UNKNOWN  # "signed by both" contradicts another statement
    for status in (SignatureStatus.SIGNED_PARTIAL, SignatureStatus.NOT_SIGNED):
        if status in found:
            return status
    return SignatureStatus.SIGNED_BOTH if signed_both else SignatureStatus.UNKNOWN
