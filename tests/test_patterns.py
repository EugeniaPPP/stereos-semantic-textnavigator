import re
from datetime import date
from decimal import Decimal

import pytest

from textnav.patterns import MONEY, find_dates, normalize_number, parse_date, parse_money


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("1 200 000 (один миллион двести тысяч) рублей", Decimal("1200000")),
        ("840 000 рублей", Decimal("840000")),
        ("1\u00a0450\u00a0000 руб.", Decimal("1450000")),
        ("1 200 000,50 руб.", Decimal("1200000.50")),
        ("252000 ₽", Decimal("252000")),
    ],
)
def test_money_is_found_and_parsed(text, amount):
    match = re.search(MONEY, f"Сумма составляет {text}, включая НДС.")

    assert match is not None
    assert parse_money(match.group()) == amount


@pytest.mark.parametrize(
    "text", ["0,1% стоимости", "20 календарных дней", "приложение № 1", "до 2026 года", "рубрика"]
)
def test_non_money_is_ignored(text):
    assert re.search(MONEY, text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15.04.2026", date(2026, 4, 15)),
        ("5.3.2026", date(2026, 3, 5)),
        ("30 апреля 2026", date(2026, 4, 30)),
        ("«1» марта 2026", date(2026, 3, 1)),
        ("1 Марта 2026", date(2026, 3, 1)),
        ("31.02.2026", None),
        ("не дата", None),
    ],
)
def test_date_is_parsed(text, expected):
    assert parse_date(text) == expected


def test_dates_are_found_in_order_with_offsets():
    text = "перенести срок с 20.03.2026 на 27.03.2026 из-за задержки"

    found = find_dates(text)

    assert [value for value, _, _ in found] == [date(2026, 3, 20), date(2026, 3, 27)]
    assert [text[start:end] for _, start, end in found] == ["20.03.2026", "27.03.2026"]


def test_invalid_date_is_found_without_value():
    assert [value for value, _, _ in find_dates("срок 31.02.2026")] == [None]


def test_date_inside_longer_number_is_ignored():
    assert find_dates("код 115.04.20261") == []


@pytest.mark.parametrize(
    ("raw", "normalized"), [("stn–101", "STN-101"), (" A-7 ", "A-7"), ("123/2026", "123/2026")]
)
def test_contract_number_is_normalized(raw, normalized):
    assert normalize_number(raw) == normalized
