"""Shared regex fragments and parsers: money amounts, dates, contract numbers.

Fragments have no capturing groups, so rules can embed them into their own patterns.
Compile patterns that embed ``DATE`` with ``re.IGNORECASE`` (month names may be capitalized).
"""

import re
from datetime import date
from decimal import Decimal

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

# --- money --------------------------------------------------------------------

_DIGIT_GROUP_SPACE = "[ \u00a0\u202f]"
_AMOUNT = rf"(?:\d{{1,3}}(?:{_DIGIT_GROUP_SPACE}\d{{3}})+|\d+)(?:,\d{{1,2}})?"
_RUBLES = r"(?:рубл(?:ей|я|ь)(?![а-яё])|руб(?![а-яё])\.?|₽)"

# "1 000 000 (один миллион) рублей", "500 000 руб.", "75000 ₽"
MONEY = rf"(?<![\d.,]){_AMOUNT}(?:\s*\([^()]*\))?\s*{_RUBLES}"

_AMOUNT_PARTS = re.compile(rf"(\d{{1,3}}(?:{_DIGIT_GROUP_SPACE}\d{{3}})+|\d+)(?:,(\d{{1,2}}))?")


def parse_money(text: str) -> Decimal | None:
    """Parse the leading amount of a ``MONEY`` match (digits only; words are ignored)."""
    match = _AMOUNT_PARTS.search(text)
    if match is None:
        return None
    integer = re.sub(r"\D", "", match.group(1))
    return Decimal(f"{integer}.{match.group(2)}") if match.group(2) else Decimal(integer)


# --- dates --------------------------------------------------------------------

_MONTH_NAMES = "|".join(_MONTHS)

# "31.12.2030", "5.3.2030", "30 апреля 2030", "«1» марта 2030"
DATE = (
    rf"(?<![\d.])(?:\d{{1,2}}\.\d{{1,2}}\.\d{{4}}|«?\d{{1,2}}»?\s+(?:{_MONTH_NAMES})\s+\d{{4}})"
    r"(?!\d)"
)

_DATE_RE = re.compile(DATE, re.IGNORECASE)
_NUMERIC_DATE_PARTS = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_TEXT_DATE_PARTS = re.compile(r"«?(\d{1,2})»?\s+([а-яё]+)\s+(\d{4})", re.IGNORECASE)


def parse_date(text: str) -> date | None:
    """Parse a ``DATE`` match. Returns None for text that is not a valid calendar date."""
    text = text.strip()
    if match := _NUMERIC_DATE_PARTS.fullmatch(text):
        day, month, year = (int(part) for part in match.groups())
    elif (match := _TEXT_DATE_PARTS.fullmatch(text)) and match.group(2).lower() in _MONTHS:
        day, month, year = int(match.group(1)), _MONTHS[match.group(2).lower()], int(match.group(3))
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[date | None, int, int]]:
    """All date-like fragments as (parsed value or None, start, end)."""
    return [(parse_date(m.group()), m.start(), m.end()) for m in _DATE_RE.finditer(text)]


# --- contract numbers ---------------------------------------------------------

NUMBER_SIGN = r"(?:№|N(?:o\.?)?(?=[\s\d]))"
NUMBER = r"[A-Za-zА-Яа-яЁё0-9]+(?:[-–—/.][A-Za-zА-Яа-яЁё0-9]+)*"


def normalize_number(raw: str) -> str:
    """Canonical form used to link documents: upper case, ASCII hyphen."""
    return re.sub(r"[–—]", "-", raw.strip()).upper()


def looks_like_number(token: str, after_number_sign: bool) -> bool:
    """A number has a digit; without a preceding "№" it must also have a letter ("AB-7")."""
    has_digit = any(char.isdigit() for char in token)
    has_letter = any(char.isalpha() for char in token)
    return has_digit and (after_number_sign or has_letter)
