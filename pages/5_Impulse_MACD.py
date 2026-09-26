import streamlit as st

from src.navigation import render_navigation
from src.impulse_panel import render_impulse_panel

st.set_page_config(page_title="Impulse MACD 黃金交叉選股", page_icon="📈", layout="wide")
render_navigation()
render_impulse_panel()
