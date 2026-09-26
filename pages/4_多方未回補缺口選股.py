import streamlit as st

from src.navigation import render_navigation
from src.unfilled_gap_panel import render_unfilled_panel

st.set_page_config(page_title="Unfilled Bullish Gap Scanner", page_icon="📊", layout="wide")
render_navigation()
render_unfilled_panel()
