import streamlit as st

from src.navigation import render_navigation
from src.bull_flag_gap_panel import render_gap_panel

st.set_page_config(page_title="Bull Flag Gap Breakout", page_icon="📈", layout="wide")
render_navigation()
render_gap_panel()
