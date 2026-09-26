"""Shared sidebar labels for the existing Streamlit pages."""
import streamlit as st


def render_navigation():
    st.sidebar.page_link("app.py", label="stock-dashboard Apps")
    st.sidebar.page_link("pages/5_Impulse_MACD.py", label="Impulse MACD 黃金交叉選股")
    st.sidebar.page_link("pages/1_台股下降旗形選股.py", label="台股下降旗形選股")
    st.sidebar.page_link("pages/3_下降旗形多方缺口突破.py", label="下降旗形多方缺口突破")
    st.sidebar.page_link("pages/4_多方未回補缺口選股.py", label="多方未回補缺口選股")
    st.sidebar.page_link("pages/2_下降旗形策略回測.py", label="下降旗形策略回測")
