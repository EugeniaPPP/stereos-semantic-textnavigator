"""Guard: values from documents/ must not appear in the application code (docs/TASK.md).

Contract numbers, company names, amounts, dates and file names of the sample documents are
collected from documents/ itself, then searched for in textnav/ and app.py (comments too).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_FILES = sorted([*ROOT.glob("textnav/**/*.py"), ROOT / "app.py"])


def _sample_values() -> set[str]:
    values: set[str] = set()
    for path in sorted((ROOT / "documents").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        values.add(path.name)
        values.add(path.stem)
        values |= set(re.findall(r"\b[A-Z]{2,}-\d+\b", text))  # contract numbers
        values |= {name for name in re.findall(r"«([^»]+)»", text) if len(name) > 3}  # companies
        values |= set(re.findall(r"\b\d{2}\.\d{2}\.\d{4}\b", text))  # dates
        for amount in re.findall(r"\b\d{1,3}(?: \d{3})+\b", text):  # amounts
            values |= {amount, amount.replace(" ", ""), amount.replace(" ", "_")}
    return values


def test_sample_values_are_collected():
    values = _sample_values()

    assert {"STN-101", "840 000", "840000", "20.03.2026", "01_contract.txt"} <= values


def test_application_code_contains_no_sample_values():
    values = _sample_values()
    leaks = [
        (path.relative_to(ROOT).as_posix(), value)
        for path in CODE_FILES
        for value in sorted(values)
        if value in path.read_text(encoding="utf-8")
    ]

    assert leaks == []


def test_sources_have_no_invisible_characters():
    """NBSP and BOM must be written as escapes (\\u00a0), so that code reads unambiguously."""
    sources = [*CODE_FILES, *sorted(ROOT.glob("tests/**/*.py"))]
    found = [
        path.relative_to(ROOT).as_posix()
        for path in sources
        if any(char in path.read_text(encoding="utf-8") for char in "\u00a0\u202f\ufeff")
    ]

    assert found == []
