"""Streamlit discovers this page alongside the existing app.py dashboard."""
import streamlit as st

from src.bull_flag_panel import render_bull_flag_panel
from src.navigation import render_navigation

st.set_page_config(page_title="台股下降旗形選股", page_icon="📈", layout="wide")
render_navigation()
render_bull_flag_panel()
