"""Extraction of contract terms (total cost, delivery date, ...) driven by a field registry.

A field is described by a ``FieldSpec``; the engine below is generic and knows no field.

* Contracts: rules run over every sentence.
* Change documents (amendments, drafts, letters): rules run only inside change clauses,
  i.e. paragraphs with a change intent ("изложить в редакции", "изменить", "перенести", ...).
  A field mentioned in a change clause without a recognizable value is UNPARSED, so the
  resolver never silently keeps the previous value.

Veto words ("аванс", "оплата", ...) reject a rule match when they occur in the sentence
before the end of the value; a sentence with a veto word anywhere is also ignored for the
"mentioned / not parsed" checks.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from textnav.evidence import cite
from textnav.model import (
    ChangeClause,
    Citation,
    DocType,
    Extraction,
    ExtractionState,
    Paragraph,
    SourceDocument,
    Span,
)
from textnav.patterns import DATE, MONEY, parse_date, parse_money

_I = re.IGNORECASE


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]  # must define the named group "value"


def rule(name: str, regex: str) -> Rule:
    return Rule(name, re.compile(regex, _I))


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Everything the engine needs to know about one extractable field."""

    name: str
    label: str  # user-facing name
    parse: Callable[[str], Any]  # text of the "value" group -> value, or None if unreadable
    rules: tuple[Rule, ...]  # ordered from specific to general; the first matching rule wins
    veto: re.Pattern[str]  # words that make a sentence speak about something else
    mention: re.Pattern[str]  # the field is mentioned
    value_hint: re.Pattern[str]  # a value-like fragment is present ("руб", a date, ...)
    absent: re.Pattern[str]  # the text says that the value is not specified
    in_table: bool = True  # shown as a column of the main table


# --- default fields -----------------------------------------------------------

_NOT_SPECIFIED = r"не\s+(?:указан|установлен|определен|определён|согласован)\w*"

_COST_SUBJECT = (
    r"(?<![А-Яа-яЁё])(?:(?:общ|итогов)\w*\s+)?(?:стоимост\w*|цен[аыу](?![а-яё])|сумм[аыу](?![а-яё]))"
    r"(?:\s+(?:поставки|договора|товара|товаров|оборудования|продукции))?"
)
_COST_LINK = r"\s*(?:составляет|составит|составила|равна|равняется|—|–|-|:)\s*"

TOTAL_COST = FieldSpec(
    name="total_cost",
    label="Сумма",
    parse=parse_money,
    rules=(
        rule(
            "change_to",
            rf"(?:измени|установи)\w*\s+(?:размер\s+)?{_COST_SUBJECT}"
            rf"(?:\s+с\s+{MONEY})?\s+на\s+(?P<value>{MONEY})",
        ),
        rule(
            "change_up_to",
            rf"(?:увелич|уменьш|измени)\w*\s+(?:размер\s+)?{_COST_SUBJECT}"
            rf"(?:\s+с\s+{MONEY})?\s+до\s+(?P<value>{MONEY})",
        ),
        rule("statement", rf"{_COST_SUBJECT}{_COST_LINK}(?P<value>{MONEY})"),
        rule("on_amount", rf"\bна\s+(?:общую\s+)?сумму\s+(?P<value>{MONEY})"),
    ),
    veto=re.compile(
        r"аванс|предоплат|лимит|бюджет|неустойк|штраф|\bпен[иья]\b|задат|обеспечени", _I
    ),
    mention=re.compile(
        r"(?<![А-Яа-яЁё])(?:стоимост|цен[аыуе](?![а-яё])|сумм[аыу]\s+договора)"
        r"|\bна\s+(?:общую\s+)?сумму",
        _I,
    ),
    value_hint=re.compile(r"руб|₽", _I),
    absent=re.compile(rf"{_NOT_SPECIFIED}|определя\w*\s+(?:в\s+)?(?:спецификаци|приложени)", _I),
)

_DELIVERY_TERM = r"срок\w*\s+поставки(?:\s+(?:товара|оборудования|продукции))?"

DELIVERY_DATE = FieldSpec(
    name="delivery_date",
    label="Срок поставки",
    parse=parse_date,
    rules=(
        rule(
            "change_to",
            rf"(?:перенести|перенос\w*|измени\w*|продли\w*|установи\w*)\s+(?:окончательн\w+\s+)?"
            rf"{_DELIVERY_TERM}(?:\s+с\s+{DATE})?\s+(?:на|до|по)\s+(?P<value>{DATE})",
        ),
        rule(
            "subject_change",
            rf"{_DELIVERY_TERM}\s+(?:переносится|изменяется|продлевается|устанавливается)"
            rf"(?:\s+с\s+{DATE})?\s+(?:на|до|по)\s+(?P<value>{DATE})",
        ),
        rule(
            "deadline",
            rf"(?:поставить|поставк[аиу]|осуществить\s+поставку|{_DELIVERY_TERM})"
            rf".{{0,80}}?\b(?:не\s+позднее|до|по)\s+(?P<value>{DATE})",
        ),
        rule("term_value", rf"{_DELIVERY_TERM}\s*(?:—|–|-|:|составляет)\s*(?P<value>{DATE})"),
    ),
    veto=re.compile(
        r"оплат|платеж|платёж|приемк|приёмк|неустойк|гарантийн|аванс|претензи"
        r"|договор\w*(?:\s+поставки)?\s+(?:действует|вступает)|срок\w*\s+действия|вступ\w*\s+в\s+силу",
        _I,
    ),
    mention=re.compile(
        r"срок\w*\s+поставки|поставить|поставк[аиу]\s+(?:\w+\s+){0,2}?(?:осуществля|производ|должн)"
        r"|осуществ\w*\s+поставк|дат\w*\s+поставки",
        _I,
    ),
    value_hint=re.compile(rf"{DATE}|\bв\s+течение\b|\d+\s+(?:календарн|рабоч)\w*\s+дн", _I),
    absent=re.compile(_NOT_SPECIFIED, _I),
)

TERM_REGISTRY: tuple[FieldSpec, ...] = (TOTAL_COST, DELIVERY_DATE)

# --- change clauses -------------------------------------------------------------

# Verbs only: the nouns "изменения", "без изменений" do not express an intent to change.
_CHANGE_INTENT = re.compile(
    r"(?<!не\s)\b(?:изложи\w*|измени(?:ть|ли|ть?ся)\b|изменя\w*|перен[её]с\w*|перенос\w*|перенести"
    r"|увелич\w*|уменьш\w*|замени\w*|продл\w*|установи\w*|дополнить\b|исключить\b)",
    _I,
)
_HEADER_LINE = re.compile(
    r"(?:Дата|Статус|Тема|От|Кому|Копия|Покупатель|Поставщик|Предмет)\b[^:]{0,20}:", _I
)
_TARGET_CLAUSE = re.compile(r"(?:пункт\w*|п\.)\s*(?P<clause>\d+(?:\.\d+)*)", _I)


def extract_terms(
    doc: SourceDocument, doc_type: DocType, registry: tuple[FieldSpec, ...] = TERM_REGISTRY
) -> tuple[dict[str, Extraction], tuple[ChangeClause, ...]]:
    if doc_type is DocType.CONTRACT:
        return {spec.name: _contract_term(doc, spec) for spec in registry}, ()

    clauses = [p for p in doc.paragraphs if _is_change_clause(doc, p)]
    touched: dict[int, list[str]] = {p.index: [] for p in clauses}
    terms: dict[str, Extraction] = {}
    for spec in registry:
        values: list[tuple[Any, Citation]] = []
        unparsed: list[Citation] = []
        for paragraph in clauses:
            scan = _scan(doc, spec, paragraph)
            values += scan.values
            unparsed += scan.unparsed
            if not scan.values and scan.mentioned and not scan.unparsed:
                unparsed.append(_paragraph_citation(doc, paragraph))
            if scan.values or scan.mentioned or scan.unparsed:
                touched[paragraph.index].append(spec.name)
        terms[spec.name] = _combine(spec.name, values, unparsed)

    change_clauses = tuple(
        ChangeClause(
            citation=_paragraph_citation(doc, p),
            target_clause=_target_clause(p.text),
            fields=tuple(touched[p.index]),
        )
        for p in clauses
    )
    return terms, change_clauses


@dataclass(slots=True)
class _Scan:
    values: list[tuple[Any, Citation]] = field(default_factory=list)
    unparsed: list[Citation] = field(default_factory=list)  # value-like text that was not read
    absent: list[Citation] = field(default_factory=list)
    mentioned: bool = False


def _scan(doc: SourceDocument, spec: FieldSpec, paragraph: Paragraph) -> _Scan:
    scan = _Scan()
    for span in paragraph.sentences:
        sentence = doc.text[span.start : span.end]
        matches = _first_rule_matches(spec, sentence)
        for match in matches:
            value = spec.parse(match.group("value"))
            citation = cite(
                doc,
                paragraph,
                span,
                span.start + match.start("value"),
                span.start + match.end("value"),
            )
            if value is None:
                scan.unparsed.append(citation)
            else:
                scan.values.append((value, citation))
        if matches:
            scan.mentioned = True
            continue
        if spec.veto.search(sentence) or not spec.mention.search(sentence):
            continue
        scan.mentioned = True
        if spec.value_hint.search(sentence):
            scan.unparsed.append(cite(doc, paragraph, span))
        elif spec.absent.search(sentence):
            scan.absent.append(cite(doc, paragraph, span))
    return scan


def _first_rule_matches(spec: FieldSpec, sentence: str) -> list[re.Match[str]]:
    for current in spec.rules:
        matches = [
            m
            for m in current.pattern.finditer(sentence)
            if not spec.veto.search(sentence[: m.end("value")])
        ]
        if matches:
            return matches
    return []


def _contract_term(doc: SourceDocument, spec: FieldSpec) -> Extraction:
    values: list[tuple[Any, Citation]] = []
    unparsed: list[Citation] = []
    absent: list[Citation] = []
    for paragraph in doc.paragraphs:
        scan = _scan(doc, spec, paragraph)
        values += scan.values
        unparsed += scan.unparsed
        absent += scan.absent
    if values:
        return _combine(spec.name, values, [])
    if unparsed:
        return Extraction(spec.name, ExtractionState.UNPARSED, citations=tuple(unparsed))
    if absent:
        return Extraction(spec.name, ExtractionState.STATED_ABSENT, citations=tuple(absent))
    return Extraction(spec.name, ExtractionState.NOT_FOUND)


def _combine(name: str, values: list[tuple[Any, Citation]], unparsed: list[Citation]) -> Extraction:
    distinct = list(dict.fromkeys(value for value, _ in values))
    citations = tuple(dict.fromkeys([c for _, c in values] + unparsed))
    if len(distinct) > 1 or (distinct and unparsed):
        return Extraction(name, ExtractionState.AMBIGUOUS, citations=citations)
    if distinct:
        return Extraction(name, ExtractionState.FOUND, distinct[0], citations)
    if unparsed:
        return Extraction(name, ExtractionState.UNPARSED, citations=citations)
    return Extraction(name, ExtractionState.NOT_FOUND)


def _is_change_clause(doc: SourceDocument, paragraph: Paragraph) -> bool:
    if paragraph.index == 0:
        return False  # the title
    if paragraph.clause is None and _HEADER_LINE.match(paragraph.text):
        return False
    return any(_CHANGE_INTENT.search(doc.text[s.start : s.end]) for s in paragraph.sentences)


def _target_clause(text: str) -> str | None:
    match = _TARGET_CLAUSE.search(text)
    return match.group("clause") if match else None


def _paragraph_citation(doc: SourceDocument, paragraph: Paragraph) -> Citation:
    return cite(doc, paragraph, Span(paragraph.start, paragraph.end))
