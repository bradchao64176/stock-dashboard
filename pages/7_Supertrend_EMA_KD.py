import streamlit as st
from src.navigation import render_navigation
from src.supertrend_panel import render_supertrend_panel

st.set_page_config(page_title='Supertrend + EMA200 + KD Scanner',layout='wide')
render_navigation()
render_supertrend_panel()
