"""Shared controls with persistent per-page settings; no scanner/data calls."""
import streamlit as st
from services.liquidity_filter import (LiquidityConfig, DEFAULT_MIN_TRADING_VALUE,
    TRADING_VALUE_INPUT_STEP, filter_trading_value, format_trading_value)

PRESETS = {"5千萬": 50_000_000, "1億": DEFAULT_MIN_TRADING_VALUE, "2億": 200_000_000, "5億": 500_000_000}


def _save(base, field):
    st.session_state[base + field] = st.session_state["_" + base + field]


def _preset(base):
    value = PRESETS.get(st.session_state["_" + base + "preset"])
    if value is not None:
        st.session_state[base + "minimum"] = value
        st.session_state["_" + base + "minimum"] = value


def render_liquidity_control(scanner_id):
    base = "liquidity_" + scanner_id + "_"
    # Persistent values are separate from widget keys, which Streamlit removes
    # when navigating away from a page.
    for field, default in (("enabled", True), ("minimum", DEFAULT_MIN_TRADING_VALUE)):
        st.session_state.setdefault(base + field, default)
        if "_" + base + field not in st.session_state:
            st.session_state["_" + base + field] = st.session_state[base + field]
    with st.expander("💰 最低成交值篩選", expanded=True):
        enabled = st.checkbox("啟用最低成交值過濾", key="_" + base + "enabled", on_change=_save, args=(base, "enabled"))
        st.selectbox("成交值快速設定", ["自訂", *PRESETS], key="_" + base + "preset", on_change=_preset, args=(base,))
        minimum = st.number_input("最低成交值（NT$）", min_value=0, step=TRADING_VALUE_INPUT_STEP,
                                  key="_" + base + "minimum", on_change=_save, args=(base, "minimum"))
        st.caption("最低成交值：" + format_trading_value(minimum))
    return LiquidityConfig(enabled, minimum)


def show_liquidity_stats(stats):
    st.caption(f"技術條件符合：{stats['technical']} 檔 · 成交值 < {format_trading_value(stats['minimum'])} 排除：{stats['below_minimum']} 檔 · "
               f"成交值 UNKNOWN 排除：{stats['unknown_excluded']} 檔 · 流動性篩選後：{stats['remaining']} 檔" + ("（過濾已停用）" if not stats['enabled'] else ""))


def apply_liquidity_controls(scanner_id, candidates, histories):
    config = render_liquidity_control(scanner_id)
    result, stats = filter_trading_value(candidates, histories, config)
    show_liquidity_stats(stats)
    return result
