"""Streamlit entry point: ``streamlit run app.py``.

STN_PRELOAD_DIR=<folder> preloads all *.txt files of the folder (development and demo helper).
"""

import os
from datetime import date

import streamlit as st

from textnav.ui.main_view import render

DEFAULT_CHECK_DATE = date(2026, 3, 10)  # PRD, decision D1

st.set_page_config(page_title="Semantic TextNavigator", page_icon="📄", layout="wide")
render(DEFAULT_CHECK_DATE, preload_dir=os.environ.get("STN_PRELOAD_DIR"))
