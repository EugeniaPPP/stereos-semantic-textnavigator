"""Group analyzed documents by contract number; route the rest to "Документы, требующие внимания".

Ordering uses content-derived keys only (contract number, document date, content hash),
so neither file names nor upload order change the result.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from textnav.model import (
    AttentionItem,
    AttentionReason,
    ContractGroup,
    DocType,
    DocumentAnalysis,
    ExtractionState,
)

MSG_DUPLICATE = "Тот же текст, что и в файле «{first}»: документ учтён один раз."
MSG_UNKNOWN_TYPE = (
    "Тип документа не распознан: ожидаются договор, допсоглашение, проект изменения или письмо."
)
MSG_AMBIGUOUS_LINK = "Документ ссылается на несколько разных договоров: связь не установлена."
MSG_NO_LINK = "Не удалось определить, к какому договору относится документ."


def link(analyses: Iterable[DocumentAnalysis]) -> tuple[list[ContractGroup], list[AttentionItem]]:
    attention: list[AttentionItem] = []
    unique: dict[str, DocumentAnalysis] = {}
    for analysis in sorted(analyses, key=lambda a: (a.source.doc_id, a.source.filename)):
        first = unique.setdefault(analysis.source.doc_id, analysis)
        if first is not analysis:
            message = MSG_DUPLICATE.format(first=first.source.filename)
            attention.append(_item(AttentionReason.DUPLICATE, message, analysis))

    contracts: dict[str, list[DocumentAnalysis]] = defaultdict(list)
    changes: dict[str, list[DocumentAnalysis]] = defaultdict(list)
    for analysis in unique.values():
        meta = analysis.meta
        if meta.doc_type is DocType.UNKNOWN:
            attention.append(_item(AttentionReason.UNKNOWN_TYPE, MSG_UNKNOWN_TYPE, analysis))
        elif meta.contract_number.state is ExtractionState.AMBIGUOUS:
            attention.append(_item(AttentionReason.UNLINKED, MSG_AMBIGUOUS_LINK, analysis))
        elif meta.contract_number.state is not ExtractionState.FOUND:
            attention.append(_item(AttentionReason.UNLINKED, MSG_NO_LINK, analysis))
        elif meta.doc_type is DocType.CONTRACT:
            contracts[meta.contract_number.value].append(analysis)
        else:
            changes[meta.contract_number.value].append(analysis)

    groups = [
        ContractGroup(
            number=number,
            contracts=tuple(sorted(contracts[number], key=document_order)),
            changes=tuple(sorted(changes[number], key=document_order)),
        )
        for number in sorted(contracts.keys() | changes.keys(), key=natural_key)
    ]
    reasons = list(AttentionReason)
    attention.sort(key=lambda item: (reasons.index(item.reason), item.analysis.source.doc_id))
    return groups, attention


def document_order(analysis: DocumentAnalysis) -> tuple[date, str]:
    doc_date = analysis.meta.doc_date
    return (
        doc_date.value if doc_date.state is ExtractionState.FOUND else date.min,
        analysis.source.doc_id,
    )


def natural_key(number: str) -> list[tuple[int, int | str]]:
    """Natural order: "STN-12" sorts before "STN-110"."""
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", number)
        if part
    ]


def _item(reason: AttentionReason, message: str, analysis: DocumentAnalysis) -> AttentionItem:
    return AttentionItem(reason, message, analysis.source.filename, analysis)
