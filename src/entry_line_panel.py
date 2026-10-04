"""Shared snapshot-only Entry UI and explicit-click-only LINE component."""
import hashlib
import uuid
import pandas as pd
import streamlit as st

from services.scanner_entry_service import analyze_scanner_candidates, current_backtest_candidates, SCANNER_NAMES
from services.entry_line_notification_service import build_preview, send_preview, get_line_eligible_candidates
from src.entry_timing_panel import render_entry_timing_panel
from src.impulse_macd import ImpulseConfig

def _fingerprint(frame):
    return hashlib.sha256(frame.to_json(date_format="iso").encode()).hexdigest()


def _manual_click(scanner_id, event_id, preview):
    """Callback registered only on the explicit send button. Consume before IO."""
    key = scanner_id + "_line_handled_events"
    handled = st.session_state.setdefault(key, set())
    if event_id in handled:
        return
    handled.add(event_id)
    if not preview["messages"] or preview["scanner_id"] != scanner_id:
        return
    saved = st.session_state.get(scanner_id + "_entry_results")
    metadata = st.session_state.get(scanner_id + "_entry_metadata", {})
    if (saved is None or _fingerprint(saved) != preview.get("analysis_fingerprint")
            or metadata.get("analysis_timestamp") != preview.get("analysis_timestamp")):
        st.session_state[scanner_id + "_line_outcome"] = dict(ok=False, stocks_sent=0, messages_sent=0,
            error="Entry Timing snapshot changed. Review the updated analysis and preview before sending.")
        return
    try:
        st.session_state[scanner_id + "_line_outcome"] = send_preview(preview, event_id)
    except Exception:
        # Do not display arbitrary exceptions that could contain request secrets.
        st.session_state[scanner_id + "_line_outcome"] = dict(ok=False, stocks_sent=0, messages_sent=0,
            error="LINE sending failed; delivery may be uncertain. No automatic retry was made.")


def render_entry_line_push_button(scanner_id, results_df):
    if not results_df.empty and "scanner_id" in results_df and not results_df.scanner_id.eq(scanner_id).all():
        raise ValueError("Entry Timing snapshot does not belong to this page")
    st.subheader("📲 LINE 進場候選通知")
    # Freeze the timestamp/content across reruns. The preview is exactly the
    # payload passed into the button callback, including message part numbers.
    fingerprint = _fingerprint(results_df)
    st.session_state[scanner_id + "_entry_results"] = results_df
    metadata = st.session_state.get(scanner_id + "_entry_metadata", {})
    version = ("all_displayed_rows_v2", fingerprint, metadata.get("analysis_timestamp"))
    eligible_count = len(get_line_eligible_candidates(results_df))
    packet_key = scanner_id + "_line_preview"
    if st.session_state.get(packet_key, {}).get("version") != version:
        try:
            preview = build_preview(results_df, scanner_id, now=metadata.get("analysis_timestamp"))
            preview["analysis_fingerprint"] = fingerprint
            preview["analysis_timestamp"] = metadata.get("analysis_timestamp")
        except (ValueError, TypeError, KeyError):
            preview = dict(scanner_id=scanner_id, messages=[], counts=[], candidate_count=eligible_count, analysis_fingerprint=fingerprint)
            st.warning("Unable to prepare valid LINE messages for this result.")
        st.session_state[packet_key] = dict(version=version, preview=preview)
        st.session_state.pop(scanner_id + "_line_outcome", None)
    preview = st.session_state[packet_key]["preview"]
    if len(results_df) != eligible_count or preview["candidate_count"] != len(results_df):
        st.error("LINE candidate count differs from displayed Entry Timing analysis. Sending disabled.")
        return
    st.write(f"Entry Timing Analysis：{len(results_df)} 檔")
    if metadata:
        st.caption("LINE 使用此分析結果：" + pd.Timestamp(metadata["analysis_timestamp"]).strftime("%Y/%m/%d %H:%M:%S"))
    st.write(f"LINE 發送候選：{preview['candidate_count']} 檔")
    if eligible_count == 0:
        st.info("目前沒有符合進場條件的股票。")
    with st.expander("📋 預覽 LINE 訊息"):
        for text in preview["messages"]:
            st.text(text)
    token_key = scanner_id + "_line_event"
    token = st.session_state.get(token_key)
    if token is None or token in st.session_state.get(scanner_id + "_line_handled_events", set()):
        token = str(uuid.uuid4())
        st.session_state[token_key] = token
    st.button(f"\U0001f4f2 \u767c\u9001 {eligible_count} \u6a94\u9032\u5834\u5019\u9078\u5230 LINE", type="primary", key="line_push_" + scanner_id,
              disabled=not preview["messages"], on_click=_manual_click,
              args=(scanner_id, token, preview))
    outcome = st.session_state.get(scanner_id + "_line_outcome")
    if outcome:
        if outcome["ok"]:
            st.success(f"LINE 發送成功。已發送 {outcome['stocks_sent']} 檔符合進場條件股票。")
        else:
            st.error("LINE 發送失敗。" + outcome["error"])
            if outcome["messages_sent"]:
                st.warning(f"已成功送出 {outcome['messages_sent']} 則／{outcome['stocks_sent']} 檔；其餘未完成。再次按鈕會重新發送全部預覽內容。")


def render_scanner_entry_section(scanner_id, candidates, snapshot, impulse_config=ImpulseConfig()):
    if scanner_id not in SCANNER_NAMES:
        raise ValueError("Unknown scanner")
    # Scanner snapshots are replaced only on a new scan. Filter values are part
    # of the signature; ordinary reruns/send callbacks reuse the exact analyses.
    threshold = st.session_state.get("liquidity_" + scanner_id + "_minimum")
    liquidity_enabled = st.session_state.get("liquidity_" + scanner_id + "_enabled")
    signature = (id(snapshot), candidates.to_json(date_format="iso"), repr(impulse_config), threshold, liquidity_enabled)
    key = scanner_id + "_entry_results"
    if st.session_state.get(scanner_id + "_entry_signature") != signature:
        st.session_state[key] = analyze_scanner_candidates(scanner_id, candidates, snapshot.get("details", {}), impulse_config)
        st.session_state[scanner_id + "_entry_signature"] = signature
        st.session_state[scanner_id + "_entry_metadata"] = dict(
            analysis_timestamp=pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
            scanner_name=SCANNER_NAMES[scanner_id], trading_value_threshold=threshold,
            trading_value_filter_enabled=liquidity_enabled, candidate_count=len(st.session_state[key]))
    results = st.session_state[key]
    metadata = st.session_state[scanner_id + "_entry_metadata"]
    st.caption("Entry Timing Analysis 更新時間：" + pd.Timestamp(metadata["analysis_timestamp"]).strftime("%Y/%m/%d %H:%M:%S"))
    st.caption(f"分析策略：{metadata['scanner_name']} · 成交值門檻：{metadata['trading_value_threshold']} · 過濾啟用：{metadata['trading_value_filter_enabled']}")
    render_entry_timing_panel(dict(candidates=candidates, details=snapshot.get("details", {})), impulse_config,
                              entry_results=results, key_prefix=scanner_id + "_entry")
    render_entry_line_push_button(scanner_id, results)


def render_backtest_current_entries(liquidity_config=None):
    st.caption("LINE 僅使用今日執行的台股下降旗形選股之最新已完成日線突破候選；不使用歷史回測交易。請先在選股頁執行掃描。")
    snapshot = st.session_state.get("bull_flag_snapshot")
    candidates, _ = current_backtest_candidates(snapshot)
    from services.liquidity_filter import filter_trading_value, LiquidityConfig
    from src.liquidity_panel import show_liquidity_stats
    candidates, stats = filter_trading_value(candidates, snapshot.get("details", {}) if snapshot else {},
                                             liquidity_config if liquidity_config is not None else LiquidityConfig())
    show_liquidity_stats(stats)
    render_scanner_entry_section("bear_flag_backtest", candidates, snapshot if snapshot is not None else {})
