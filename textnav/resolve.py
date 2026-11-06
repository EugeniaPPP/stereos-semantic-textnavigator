"""Effective contract terms on the check date: deterministic business rules.

The rules are documented in docs/ARCHITECTURE.md («Статусы на дату проверки D»). In short:
only amendments signed by both parties and in force on the check date change the terms;
letters and drafts are proposals; anything unreliable is NEEDS_REVIEW, never a guess.
"""

from dataclasses import replace
from datetime import date
from itertools import groupby

from textnav.formatting import describe_extraction, document_label, format_date, lower_first
from textnav.model import (
    Alert,
    AlertCode,
    AttentionItem,
    AttentionReason,
    ChangeClause,
    ChangeDoc,
    ChangeStatus,
    ContractGroup,
    ContractStatus,
    ContractView,
    DocType,
    DocumentAnalysis,
    Extraction,
    ExtractionState,
    SignatureStatus,
    TermResolution,
    TermValue,
    ValueState,
)
from textnav.terms import TERM_REGISTRY, FieldSpec

FOUND = ExtractionState.FOUND
TOUCHING_STATES = (ExtractionState.FOUND, ExtractionState.AMBIGUOUS, ExtractionState.UNPARSED)

MSG_ORPHAN = (
    "Исходный договор {number} не загружен: документ обработан, "
    "но действующие условия не определяются."
)


def resolve_groups(
    groups: list[ContractGroup], check_date: date, registry: tuple[FieldSpec, ...] = TERM_REGISTRY
) -> tuple[list[ContractView], list[AttentionItem]]:
    views = [resolve_contract(g, check_date, registry) for g in groups if g.contracts]
    orphans = [
        AttentionItem(
            reason=AttentionReason.ORPHAN,
            message=MSG_ORPHAN.format(number=group.number),
            filename=analysis.source.filename,
            analysis=analysis,
            change=classify_change(analysis, check_date),
        )
        for group in groups
        if not group.contracts
        for analysis in group.changes
    ]
    return views, orphans


def resolve_contract(
    group: ContractGroup, check_date: date, registry: tuple[FieldSpec, ...] = TERM_REGISTRY
) -> ContractView:
    contract = group.contracts[0]
    status, status_reason = _contract_status(group, check_date)
    change_docs = tuple(classify_change(a, check_date) for a in group.changes)
    clauses = {spec.name: _field_clauses(contract, spec.name) for spec in registry}

    terms = {
        spec.name: _resolve_term(spec, contract, change_docs, clauses[spec.name], check_date)
        for spec in registry
    }
    alerts = _contract_alerts(status, status_reason)
    alerts += _change_alerts(change_docs, set().union(*clauses.values()), check_date, registry)
    if status is ContractStatus.IN_FORCE:
        alerts += [
            Alert(
                AlertCode.FIELD_NEEDS_REVIEW,
                f"{term.label}: {term.effective.reason}",
                field=term.field,
                citations=term.effective.citations,
            )
            for term in terms.values()
            if term.effective.state is ValueState.NEEDS_REVIEW
        ]
    else:
        # Values from the text stay in ``applied`` for the details view.
        state = (
            ValueState.NOT_IN_FORCE
            if status is ContractStatus.NOT_IN_FORCE
            else ValueState.NEEDS_REVIEW
        )
        shown = TermValue(state, reason=lower_first(status_reason))
        terms = {name: replace(term, effective=shown) for name, term in terms.items()}
    alerts += _supplier_alerts(contract, change_docs)

    return ContractView(
        number=group.number,
        supplier=contract.meta.supplier,
        status=status,
        status_reason=status_reason,
        contracts=group.contracts,
        terms=terms,
        change_docs=change_docs,
        alerts=tuple(alerts),
    )


# --- statuses -----------------------------------------------------------------


def _contract_status(group: ContractGroup, check_date: date) -> tuple[ContractStatus, str]:
    if len(group.contracts) > 1:
        return ContractStatus.NEEDS_REVIEW, f"Загружено несколько разных договоров № {group.number}"
    meta = group.contracts[0].meta
    signature, effective = meta.signature, meta.effective_date
    match signature.status:
        case SignatureStatus.UNKNOWN:
            return ContractStatus.NEEDS_REVIEW, "Статус подписания договора не установлен"
        case SignatureStatus.NOT_SIGNED:
            return (
                ContractStatus.NEEDS_REVIEW,
                "Документ оформлен как договор, но его статус — «не подписан»",
            )
        case SignatureStatus.SIGNED_PARTIAL:
            return ContractStatus.NOT_IN_FORCE, "Договор подписан только одной стороной"
    if signature.date is None:
        return ContractStatus.NEEDS_REVIEW, "Дата подписания договора не установлена"
    if effective.state is ExtractionState.AMBIGUOUS:
        return ContractStatus.NEEDS_REVIEW, "Дата вступления договора в силу неоднозначна"
    signed = format_date(signature.date)
    if signature.date > check_date:
        return ContractStatus.NOT_IN_FORCE, f"Договор подписан {signed} — после даты проверки"
    if effective.state is FOUND and effective.value > check_date:
        return (
            ContractStatus.NOT_IN_FORCE,
            f"Договор подписан {signed}, вступает в силу {format_date(effective.value)}",
        )
    return ContractStatus.IN_FORCE, f"Подписан обеими сторонами {signed}"


def classify_change(analysis: DocumentAnalysis, check_date: date) -> ChangeDoc:
    status, reason = _change_status(analysis, check_date)
    changes = {
        name: extraction
        for name, extraction in analysis.terms.items()
        if extraction.state in TOUCHING_STATES
    }
    return ChangeDoc(analysis, status, reason, changes)


def _change_status(analysis: DocumentAnalysis, check_date: date) -> tuple[ChangeStatus, str]:
    meta = analysis.meta
    signature = meta.signature
    if meta.doc_type is DocType.LETTER:
        return ChangeStatus.PROPOSAL, "Письмо: предложение, а не изменение договора"
    if meta.doc_type is DocType.AMENDMENT_DRAFT:
        if signature.status is SignatureStatus.SIGNED_BOTH:
            return (
                ChangeStatus.NEEDS_REVIEW,
                "Документ оформлен как проект, но его статус — «подписан обеими сторонами»",
            )
        if signature.status is SignatureStatus.SIGNED_PARTIAL:
            return ChangeStatus.PROPOSAL, "Проект подписан только одной стороной"
        return ChangeStatus.PROPOSAL, "Проект изменения не подписан"
    if meta.doc_type is not DocType.AMENDMENT:
        return ChangeStatus.NEEDS_REVIEW, "Тип документа не позволяет применить изменение"

    match signature.status:
        case SignatureStatus.SIGNED_PARTIAL:
            return ChangeStatus.PROPOSAL, "Подписано только одной стороной"
        case SignatureStatus.NOT_SIGNED:
            return (
                ChangeStatus.NEEDS_REVIEW,
                "Документ оформлен как допсоглашение, но его статус — «не подписано»",
            )
        case SignatureStatus.UNKNOWN:
            return ChangeStatus.NEEDS_REVIEW, "Статус подписания не установлен"
    if signature.date is None:
        return ChangeStatus.NEEDS_REVIEW, "Дата подписания не установлена"
    effective = meta.effective_date
    if effective.state is ExtractionState.AMBIGUOUS:
        return ChangeStatus.NEEDS_REVIEW, "Дата вступления в силу неоднозначна"
    if effective.state is not FOUND:
        return ChangeStatus.NEEDS_REVIEW, "Дата вступления в силу не установлена"
    signed, effective_on = format_date(signature.date), format_date(effective.value)
    if signature.date > check_date:
        return ChangeStatus.NOT_YET_EFFECTIVE, f"Подписано {signed} — после даты проверки"
    if effective.value > check_date:
        return ChangeStatus.NOT_YET_EFFECTIVE, f"Подписано {signed}, вступает в силу {effective_on}"
    return ChangeStatus.APPLIED, f"Подписано {signed}, вступило в силу {effective_on}"


# --- terms --------------------------------------------------------------------


def _resolve_term(
    spec: FieldSpec,
    contract: DocumentAnalysis,
    change_docs: tuple[ChangeDoc, ...],
    clauses: set[str],
    check_date: date,
) -> TermResolution:
    original = _original_value(contract, spec.name)
    applied, changed_by = original, []
    in_force = sorted(
        (c for c in change_docs if c.status is ChangeStatus.APPLIED), key=_effective_order
    )
    for effective_on, same_day in groupby(in_force, key=lambda c: _effective_order(c)[0]):
        touching = [(c, e) for c in same_day if (e := _touch(c, spec.name, clauses))]
        if touching:
            changed_by += [c.analysis.source.doc_id for c, _ in touching]
            applied = _merge_same_day(touching, effective_on)

    effective = applied
    blocking = [
        (c, e)
        for c in change_docs
        if c.status is ChangeStatus.NEEDS_REVIEW
        and _visible_on(c, check_date)
        and (e := _touch(c, spec.name, clauses))
    ]
    if blocking:
        labels = ", ".join(document_label(c.analysis) for c, _ in blocking)
        effective = TermValue(
            ValueState.NEEDS_REVIEW,
            citations=tuple(citation for _, e in blocking for citation in e.citations),
            reason=f"возможное изменение требует проверки ({labels})",
        )
    return TermResolution(spec.name, spec.label, original, applied, effective, tuple(changed_by))


def _original_value(contract: DocumentAnalysis, field: str) -> TermValue:
    extraction = contract.terms.get(field) or Extraction(field, ExtractionState.NOT_FOUND)
    doc_id, citations = contract.source.doc_id, extraction.citations
    match extraction.state:
        case ExtractionState.FOUND:
            return TermValue(ValueState.VALUE, extraction.value, citations, doc_id)
        case ExtractionState.STATED_ABSENT:
            return TermValue(
                ValueState.NO_DATA,
                citations=citations,
                source_doc_id=doc_id,
                reason="в договоре значение не указано",
            )
        case ExtractionState.UNPARSED:
            return TermValue(
                ValueState.NEEDS_REVIEW,
                citations=citations,
                source_doc_id=doc_id,
                reason="значение в договоре не распознано",
            )
        case ExtractionState.AMBIGUOUS:
            return TermValue(
                ValueState.NEEDS_REVIEW,
                citations=citations,
                source_doc_id=doc_id,
                reason="в договоре несколько разных значений",
            )
    return TermValue(
        ValueState.NO_DATA, source_doc_id=doc_id, reason="в договоре значение не найдено"
    )


def _touch(change: ChangeDoc, field: str, clauses: set[str]) -> Extraction | None:
    """How a change document affects ``field``: its extraction, or UNPARSED when it rewrites
    the contract clause holding the field without a recognizable new value."""
    extraction = change.analysis.terms.get(field)
    if extraction is not None and extraction.state in TOUCHING_STATES:
        return extraction
    hits = [c.citation for c in change.analysis.change_clauses if c.target_clause in clauses]
    if hits:
        return Extraction(field, ExtractionState.UNPARSED, citations=tuple(hits))
    return None


def _merge_same_day(touching: list[tuple[ChangeDoc, Extraction]], effective_on: date) -> TermValue:
    citations = tuple(citation for _, e in touching for citation in e.citations)
    unclear = [(c, e) for c, e in touching if e.state is not FOUND]
    if unclear:
        problems = "; ".join(
            f"{document_label(c.analysis)}: "
            + (
                "несколько разных значений"
                if e.state is ExtractionState.AMBIGUOUS
                else "новое значение не распознано"
            )
            for c, e in unclear
        )
        return TermValue(ValueState.NEEDS_REVIEW, citations=citations, reason=problems)
    values = list(dict.fromkeys(e.value for _, e in touching))
    if len(values) > 1:
        return TermValue(
            ValueState.NEEDS_REVIEW,
            citations=citations,
            reason=(
                f"изменения с одной датой вступления в силу ({format_date(effective_on)}) "
                "содержат разные значения"
            ),
        )
    return TermValue(ValueState.VALUE, values[0], citations, touching[0][0].analysis.source.doc_id)


def _field_clauses(contract: DocumentAnalysis, field: str) -> set[str]:
    """Contract clause numbers ("2.1") where the field value (or its absence) is stated."""
    extraction = contract.terms.get(field)
    if extraction is None:
        return set()
    paragraphs = contract.source.paragraphs
    return {paragraphs[c.paragraph].clause for c in extraction.citations} - {None}


def _effective_order(change: ChangeDoc) -> tuple[date, date, str]:
    meta = change.analysis.meta
    return (meta.effective_date.value, meta.signature.date, change.analysis.source.doc_id)


def _visible_on(change: ChangeDoc, check_date: date) -> bool:
    """False for a document dated after the check date: it did not exist yet."""
    doc_date = change.analysis.meta.doc_date
    return not (doc_date.state is FOUND and doc_date.value > check_date)


# --- alerts -------------------------------------------------------------------


def _contract_alerts(status: ContractStatus, reason: str) -> list[Alert]:
    if status is ContractStatus.NOT_IN_FORCE:
        return [Alert(AlertCode.CONTRACT_NOT_IN_FORCE, reason)]
    if status is ContractStatus.NEEDS_REVIEW:
        return [Alert(AlertCode.CONTRACT_NEEDS_REVIEW, reason)]
    return []


def _change_alerts(
    change_docs: tuple[ChangeDoc, ...],
    field_clauses: set[str],
    check_date: date,
    registry: tuple[FieldSpec, ...],
) -> list[Alert]:
    labels = {spec.name: spec.label for spec in registry}
    alerts: list[Alert] = []
    for change in change_docs:
        label = document_label(change.analysis)
        doc_id = change.analysis.source.doc_id
        if change.status is ChangeStatus.APPLIED:
            alerts += _applied_amendment_alerts(change, label, field_clauses)
            continue
        if change.status is not ChangeStatus.NOT_YET_EFFECTIVE and not _visible_on(
            change, check_date
        ):
            continue
        if change.status is ChangeStatus.NEEDS_REVIEW:
            message = f"{label}: {lower_first(change.reason)} — изменение не применено"
            alerts.append(Alert(AlertCode.CHANGE_NEEDS_REVIEW, message, doc_id=doc_id))
            continue

        if change.status is ChangeStatus.NOT_YET_EFFECTIVE:
            code = AlertCode.CHANGE_PENDING
            prefix = (
                f"Подписанное изменение ещё не действует — {label} ({lower_first(change.reason)})"
            )
        else:
            code = AlertCode.CHANGE_PROPOSAL
            prefix = f"Несогласованное предложение — {label}"
        if not change.changes and change.analysis.change_clauses:
            alerts.append(Alert(code, f"{prefix}: значения не распознаны", doc_id=doc_id))
        for field, extraction in change.changes.items():
            message = f"{prefix}: {labels.get(field, field)} → {describe_extraction(extraction)}"
            alerts.append(Alert(code, message, field, doc_id, extraction.citations))
    return alerts


def _applied_amendment_alerts(
    change: ChangeDoc, label: str, field_clauses: set[str]
) -> list[Alert]:
    doc_id = change.analysis.source.doc_id
    clauses = change.analysis.change_clauses
    if not clauses:
        message = f"{label}: изменения условий не распознаны — проверьте документ"
        return [Alert(AlertCode.EMPTY_AMENDMENT, message, doc_id=doc_id)]
    return [
        Alert(
            AlertCode.UNRECOGNIZED_CHANGE,
            f"{label}, {_clause_name(change, clause)}: изменение не распознано — нужна проверка",
            doc_id=doc_id,
            citations=(clause.citation,),
        )
        for clause in clauses
        if not clause.fields and clause.target_clause not in field_clauses
    ]


def _supplier_alerts(contract: DocumentAnalysis, change_docs: tuple[ChangeDoc, ...]) -> list[Alert]:
    expected = contract.meta.supplier
    if expected.state is not FOUND:
        return []
    alerts = []
    for change in change_docs:
        supplier = change.analysis.meta.supplier
        if supplier.state is FOUND and supplier.value.casefold() != expected.value.casefold():
            message = (
                f"{document_label(change.analysis)}: поставщик «{supplier.value}» "
                f"не совпадает с поставщиком договора «{expected.value}»"
            )
            alerts.append(
                Alert(
                    AlertCode.SUPPLIER_MISMATCH,
                    message,
                    doc_id=change.analysis.source.doc_id,
                    citations=supplier.citations,
                )
            )
    return alerts


def _clause_name(change: ChangeDoc, clause: ChangeClause) -> str:
    own = change.analysis.source.paragraphs[clause.citation.paragraph].clause
    name = f"п. {own}" if own else "пункт без номера"
    return f"{name} (изменяет п. {clause.target_clause} договора)" if clause.target_clause else name
