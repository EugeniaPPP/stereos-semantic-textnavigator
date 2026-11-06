"""SourceDocument -> DocumentAnalysis: metadata plus registry-driven terms."""

from textnav.meta import extract_meta
from textnav.model import DocumentAnalysis, SourceDocument
from textnav.terms import TERM_REGISTRY, FieldSpec, extract_terms


def analyze_document(
    doc: SourceDocument, registry: tuple[FieldSpec, ...] = TERM_REGISTRY
) -> DocumentAnalysis:
    meta = extract_meta(doc)
    terms, change_clauses = extract_terms(doc, meta.doc_type, registry)
    return DocumentAnalysis(source=doc, meta=meta, terms=terms, change_clauses=change_clauses)
