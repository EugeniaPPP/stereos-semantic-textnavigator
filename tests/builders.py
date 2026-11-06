"""Helpers that build synthetic documents for tests."""

from textnav.ingest import read_document
from textnav.model import SourceDocument


def make_doc(text: str, filename: str = "doc.txt") -> SourceDocument:
    result = read_document(filename, text.encode("utf-8"))
    assert isinstance(result, SourceDocument), result
    return result
