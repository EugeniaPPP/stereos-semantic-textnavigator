"""Streamlit UI via AppTest. Documents come from STN_PRELOAD_DIR: AppTest cannot upload files."""

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from tests.builders import contract_text, resolve_one
from textnav.model import TermValue, ValueState
from textnav.terms import TERM_REGISTRY
from textnav.ui.main_view import table_rows, value_text

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
DOCUMENTS = ROOT / "documents"


def _run(monkeypatch, preload_dir: Path | None = None) -> AppTest:
    if preload_dir is None:
        monkeypatch.delenv("STN_PRELOAD_DIR", raising=False)
    else:
        monkeypatch.setenv("STN_PRELOAD_DIR", str(preload_dir))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    return app


def _table(app: AppTest) -> pd.DataFrame:
    """The contracts table with non-breaking spaces turned into plain ones for readable asserts."""
    assert len(app.table) == 1
    table = app.table[0].value.reset_index(drop=True)
    return table.map(lambda cell: cell.replace("\u00a0", " "))


def _markdown(app: AppTest) -> str:
    return "\n".join(element.value for element in app.markdown)


# --- pure helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (TermValue(ValueState.NO_DATA), "Нет данных"),
        (TermValue(ValueState.NEEDS_REVIEW), "Требует проверки"),
        (TermValue(ValueState.NOT_IN_FORCE), "—"),
        (TermValue(ValueState.VALUE, date(2026, 4, 30)), "30.04.2026"),
    ],
)
def test_value_text(value, text):
    assert value_text(value) == text


def test_table_columns_follow_the_registry():
    view = resolve_one(contract_text())
    hidden = tuple(spec if spec.name != "total_cost" else _hidden(spec) for spec in TERM_REGISTRY)

    assert list(table_rows([view], TERM_REGISTRY)[0]) == [
        "Договор",
        "Поставщик",
        "Сумма",
        "Срок поставки",
        "Несогласованные изменения",
        "Статус и предупреждения",
    ]
    assert "Сумма" not in table_rows([view], hidden)[0]


def _hidden(spec):
    from dataclasses import replace

    return replace(spec, in_table=False)


# --- app ----------------------------------------------------------------------


def test_empty_state_invites_to_upload(monkeypatch):
    app = _run(monkeypatch)

    assert app.title[0].value == "Semantic TextNavigator"
    assert len(app.table) == 0
    assert "Загрузите" in app.info[0].value


def test_table_on_the_default_check_date(monkeypatch):
    table = _table(_run(monkeypatch, DOCUMENTS))

    assert list(table["Договор"]) == ["STN-101", "STN-102", "STN-103"]
    assert list(table["Поставщик"]) == [
        "ООО «Вектор Прибор»",
        "ООО «Контур Электро»",
        "ООО «ПромСнаб Сервис»",
    ]
    assert list(table["Сумма"]) == ["1 380 000 ₽", "840 000 ₽", "Нет данных"]
    assert list(table["Срок поставки"]) == ["30.04.2026", "20.03.2026", "30.04.2026"]


def test_unagreed_changes_column(monkeypatch):
    unagreed = list(_table(_run(monkeypatch, DOCUMENTS))["Несогласованные изменения"])

    assert unagreed == [
        "Проект допсоглашения № 2 от 06.03.2026: сумма → 1 450 000 ₽, срок поставки → 10.05.2026",
        "Письмо от 05.03.2026: срок поставки → 27.03.2026",
        "",
    ]


def test_question_4_filter_before_april(monkeypatch):
    app = _run(monkeypatch, DOCUMENTS)

    app.checkbox(key="filter_enabled").check().run()  # the date field becomes enabled
    app.date_input(key="filter_date").set_value(date(2026, 4, 1)).run()
    table = _table(app)

    assert list(table["Договор"]) == ["STN-102"]
    assert "27.03.2026" in table.loc[0, "Несогласованные изменения"]


def test_changing_the_check_date_recomputes_the_table(monkeypatch):
    app = _run(monkeypatch, DOCUMENTS)

    app.date_input(key="check_date").set_value(date(2026, 2, 28)).run()
    table = _table(app)

    assert table.loc[0, "Сумма"] == "1 200 000 ₽"
    assert table.loc[0, "Срок поставки"] == "15.04.2026"
    assert "после даты проверки" in table.loc[0, "Статус и предупреждения"]


def test_contract_not_in_force_shows_no_values(monkeypatch):
    app = _run(monkeypatch, DOCUMENTS)

    app.date_input(key="check_date").set_value(date(2026, 2, 7)).run()
    table = _table(app)

    assert list(table.loc[1, ["Сумма", "Срок поставки"]]) == ["—", "—"]
    assert "после даты проверки" in table.loc[1, "Статус и предупреждения"]


def test_amendment_without_contract_is_listed_for_attention(monkeypatch, tmp_path):
    shutil.copy(DOCUMENTS / "02_amendment_signed.txt", tmp_path)

    app = _run(monkeypatch, tmp_path)
    text = _markdown(app)

    assert len(app.table) == 0
    assert "02_amendment_signed.txt" in text
    assert "STN-101" in text
    assert "Сумма → 1 380 000 ₽" in text


def test_unreadable_file_is_listed_for_attention(monkeypatch, tmp_path):
    for path in DOCUMENTS.glob("*.txt"):
        shutil.copy(path, tmp_path)
    (tmp_path / "broken.txt").write_bytes(b"\x00\x01\x02")

    app = _run(monkeypatch, tmp_path)

    assert len(_table(app)) == 3
    assert "broken.txt" in _markdown(app)
