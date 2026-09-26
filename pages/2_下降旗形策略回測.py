import streamlit as st

from src.navigation import render_navigation
from src.backtest_panel import render_backtest_panel

st.set_page_config(page_title="Bull Flag Backtest", page_icon="📊", layout="wide")
render_navigation()
render_backtest_panel()
