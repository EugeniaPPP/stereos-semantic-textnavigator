from pathlib import Path

from streamlit.testing.v1 import AppTest

import textnav

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_package_imports():
    assert textnav.__version__


def test_app_starts_without_errors():
    at = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not at.exception
    assert at.title[0].value == "Semantic TextNavigator"
