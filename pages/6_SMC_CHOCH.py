import streamlit as st
from src.navigation import render_navigation
from src.smc_choch_panel import render_smc_choch_panel

st.set_page_config(page_title="SMC / CHOCH Stock Screener", page_icon="🔄", layout="wide")
render_navigation()
render_smc_choch_panel()
