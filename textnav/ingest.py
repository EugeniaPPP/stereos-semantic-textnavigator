"""Turn uploaded bytes into ``SourceDocument``: decode, normalize, split paragraphs and sentences.

A paragraph is a non-empty line. Its optional leading clause number ("2.1.") is recorded
separately, and the rest of the line is split into sentences. All offsets point into the
normalized text, so ``text[start:end]`` is always the exact quote shown to the user.
"""

import codecs
import hashlib
import re
import unicodedata
from collections.abc import Iterable

from textnav.model import Paragraph, ReadFailure, SourceDocument, Span

MSG_EMPTY = "Файл пустой."
MSG_NOT_TEXT = "Файл не похож на текстовый документ."
MSG_ENCODING = "Не удалось определить кодировку: поддерживаются UTF-8, UTF-16 с BOM и Windows-1251."
MSG_INTERNAL = "Внутренняя ошибка при чтении файла: {error}."

_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_ALLOWED_CONTROL_CHARS = frozenset("\n\t\f\v")

# "2.1.", "2.1", "3.2.1" or "1." followed by whitespace and the clause body.
# A bare number without a dot ("100 рублей") is not a clause number.
_CLAUSE = re.compile(r"(?:(\d{1,3}(?:\.\d{1,3})+)\.?|(\d{1,3})\.)\s+(?=\S)")

# Sentence boundary: terminal punctuation, optional closing quotes/brackets, whitespace,
# then an uppercase letter (optionally after an opening quote). Dates ("15.04.2026") and
# references ("п. 2.1") are not split because no whitespace + uppercase letter follows.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])([»\"')\]]*)\s+(?=[«\"(]?[A-ZА-ЯЁ])")


def read_document(filename: str, data: bytes) -> SourceDocument | ReadFailure:
    """Decode and split one file. Expected problems are returned as ``ReadFailure``."""
    is_utf16 = data.startswith(_UTF16_BOMS)
    if not is_utf16 and b"\x00" in data:
        return ReadFailure(filename, MSG_NOT_TEXT)

    try:
        text, encoding = _decode(data, is_utf16)
    except UnicodeDecodeError:
        return ReadFailure(filename, MSG_ENCODING)

    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if any(_is_forbidden_control(char) for char in text):
        return ReadFailure(filename, MSG_NOT_TEXT)
    if not text.strip():
        return ReadFailure(filename, MSG_EMPTY)

    return SourceDocument(
        doc_id=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
        filename=filename,
        text=text,
        encoding=encoding,
        paragraphs=_split_paragraphs(text),
    )


def read_documents(
    files: Iterable[tuple[str, bytes]],
) -> tuple[list[SourceDocument], list[ReadFailure]]:
    """Read every file independently: a failure in one file never blocks the others."""
    documents: list[SourceDocument] = []
    failures: list[ReadFailure] = []
    for filename, data in files:
        try:
            result = read_document(filename, data)
        except Exception as error:
            result = ReadFailure(filename, MSG_INTERNAL.format(error=type(error).__name__))
        if isinstance(result, ReadFailure):
            failures.append(result)
        else:
            documents.append(result)
    return documents, failures


def _decode(data: bytes, is_utf16: bool) -> tuple[str, str]:
    if is_utf16:
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251"), "cp1251"


def _is_forbidden_control(char: str) -> bool:
    return unicodedata.category(char) == "Cc" and char not in _ALLOWED_CONTROL_CHARS


def _split_paragraphs(text: str) -> tuple[Paragraph, ...]:
    paragraphs: list[Paragraph] = []
    for line in re.finditer(r"[^\n]+", text):
        raw = line.group()
        content = raw.strip()
        if not content:
            continue
        start = line.start() + len(raw) - len(raw.lstrip())
        end = start + len(content)

        clause_match = _CLAUSE.match(content)
        clause = (clause_match.group(1) or clause_match.group(2)) if clause_match else None
        body_start = start + (clause_match.end() if clause_match else 0)

        paragraphs.append(
            Paragraph(
                index=len(paragraphs),
                start=start,
                end=end,
                text=content,
                clause=clause,
                sentences=_split_sentences(text, body_start, end),
            )
        )
    return tuple(paragraphs)


def _split_sentences(text: str, start: int, end: int) -> tuple[Span, ...]:
    body = text[start:end]
    spans: list[Span] = []
    sentence_start = 0
    for boundary in _SENTENCE_BOUNDARY.finditer(body):
        spans.append(_trimmed_span(body, start, sentence_start, boundary.end(1)))
        sentence_start = boundary.end()
    spans.append(_trimmed_span(body, start, sentence_start, len(body)))
    return tuple(span for span in spans if span.end > span.start)


def _trimmed_span(body: str, offset: int, start: int, end: int) -> Span:
    piece = body[start:end]
    leading = len(piece) - len(piece.lstrip())
    trailing = len(piece) - len(piece.rstrip())
    return Span(offset + start + leading, offset + end - trailing)
